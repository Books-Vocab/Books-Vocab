from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import doctor  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _run(conclusion: str, days_ago: float, workflow: str = "ops-suite") -> dict:
    created = NOW - timedelta(days=days_ago)
    return {
        "workflowName": workflow,
        "conclusion": conclusion,
        "status": "completed",
        "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---- known-red CI ---------------------------------------------------------


def test_a_fresh_failure_streak_is_not_known_red_yet() -> None:
    runs = [
        _run("failure", 0.1),
        _run("failure", 0.5),
        _run("failure", 1.0),
        _run("success", 2.0),
    ]
    [finding] = doctor.evaluate_ci(runs, NOW)
    assert finding.level == "ok"


def test_three_failures_older_than_three_days_are_known_red() -> None:
    runs = [
        _run("failure", 1),
        _run("failure", 4),
        _run("failure", 9),
        _run("success", 12),
    ]
    [finding] = doctor.evaluate_ci(runs, NOW)
    assert finding.level == "block"
    assert "ops-suite" in finding.summary and "3" in finding.summary


def test_streak_stops_at_the_newest_success() -> None:
    runs = [
        _run("success", 0.2),
        _run("failure", 5),
        _run("failure", 9),
        _run("failure", 12),
    ]
    [finding] = doctor.evaluate_ci(runs, NOW)
    assert finding.level == "ok"


@pytest.mark.parametrize("neutral", ["skipped", "cancelled", "neutral", ""])
def test_skipped_cancelled_and_unfinished_runs_do_not_count(neutral: str) -> None:
    runs = [
        _run(neutral, 0.1),
        _run("failure", 4),
        _run(neutral, 5),
        _run("failure", 8),
        _run("failure", 10),
    ]
    [finding] = doctor.evaluate_ci(runs, NOW)
    assert finding.level == "block"  # three real failures remain


def test_each_workflow_is_judged_separately() -> None:
    runs = [
        _run("failure", 5, "ops-suite"),
        _run("failure", 6, "ops-suite"),
        _run("failure", 9, "ops-suite"),
        _run("success", 1, "backend-quality"),
    ]
    findings = {f.summary.split()[0]: f for f in doctor.evaluate_ci(runs, NOW)}
    assert findings["ops-suite"].level == "block"
    assert findings["backend-quality"].level == "ok"


# ---- production release gap ----------------------------------------------


@pytest.mark.parametrize(
    ("behind", "age_days", "level"),
    [
        (0, 0, "ok"),
        (150, 10, "ok"),
        (250, 10, "warn"),
        (50, 20, "warn"),
        (1500, 10, "block"),
        (50, 60, "block"),
    ],
)
def test_release_gap_levels(behind: int, age_days: int, level: str) -> None:
    finding = doctor.evaluate_release_gap("abc1234", behind, age_days)
    assert finding.level == level


def test_unknown_production_version_is_a_warning_not_a_pass() -> None:
    assert doctor.evaluate_release_gap(None, None, None).level == "warn"


# ---- registry claims ------------------------------------------------------


def test_ghost_and_ownerless_claims_are_reported(tmp_path: Path) -> None:
    alive = tmp_path / "alive"
    alive.mkdir()
    records = [
        {
            "status": "active",
            "path": str(alive),
            "codex_thread_id": "t1",
            "branch": "a",
            "external_ids": ["A"],
        },
        {
            "status": "active",
            "path": str(tmp_path / "gone"),
            "codex_thread_id": "t2",
            "branch": "b",
            "external_ids": ["B"],
        },
        {
            "status": "active",
            "path": str(alive),
            "codex_thread_id": None,
            "branch": "c",
            "external_ids": ["C"],
        },
        {
            "status": "abandoned",
            "path": str(tmp_path / "x"),
            "codex_thread_id": None,
            "branch": "d",
            "external_ids": ["D"],
        },
    ]
    finding = doctor.evaluate_registry(records)
    assert finding.level == "warn"
    text = "\n".join(finding.detail)
    assert "ghost" in text and "b" in text
    assert "ownerless" in text and "c" in text
    assert "abandoned" not in text  # terminal records are not live claims


def test_a_clean_registry_is_ok() -> None:
    assert doctor.evaluate_registry([]).level == "ok"


# ---- git ------------------------------------------------------------------


def test_git_findings() -> None:
    assert (
        doctor.evaluate_git(
            {"branch": "main", "dirty": 0, "local": "a", "origin": "a"}
        ).level
        == "ok"
    )
    assert (
        doctor.evaluate_git(
            {"branch": "main", "dirty": 0, "local": "a", "origin": "b"}
        ).level
        == "warn"
    )
    assert (
        doctor.evaluate_git(
            {"branch": "feat/x", "dirty": 0, "local": "a", "origin": "a"}
        ).level
        == "warn"
    )
    assert (
        doctor.evaluate_git(
            {"branch": "main", "dirty": 3, "local": "a", "origin": "a"}
        ).level
        == "warn"
    )


# ---- disk guard -----------------------------------------------------------


def test_disk_guard_levels() -> None:
    assert (
        doctor.evaluate_disk({"verdict": "ok", "reason": "within-bounds"}).level == "ok"
    )
    assert doctor.evaluate_disk({"verdict": "warning", "reason": "x"}).level == "warn"
    assert doctor.evaluate_disk({"verdict": "block", "reason": "y"}).level == "block"
    assert doctor.evaluate_disk(None).level == "ok"  # no guard on this machine


# ---- issue acceptance -----------------------------------------------------

BODY = """## Problem
x

## Acceptance
Pass when it works.

```sh
test -f ops/doctor.py && echo ok
```

```bash
./ops/doctor.py --json | jq -e '.ok'
```

## Delivery plan
```sh
echo not-acceptance
```
"""


def test_only_commands_inside_the_acceptance_section_are_extracted() -> None:
    assert doctor.parse_acceptance(BODY) == [
        "test -f ops/doctor.py && echo ok",
        "./ops/doctor.py --json | jq -e '.ok'",
    ]


def test_issue_without_an_acceptance_command_is_reported_as_unverifiable() -> None:
    issues = [
        {"number": 1, "title": "a", "body": BODY, "authorAssociation": "OWNER"},
        {
            "number": 2,
            "title": "b",
            "body": "## Acceptance\nprose only",
            "authorAssociation": "OWNER",
        },
    ]
    finding = doctor.evaluate_issues(issues)
    assert finding.level == "warn"
    assert any("#2" in line for line in finding.detail)


def test_acceptance_is_never_executed_for_issues_not_authored_by_the_owner() -> None:
    issues = [
        {"number": 1, "body": BODY, "authorAssociation": "OWNER"},
        {"number": 2, "body": BODY, "authorAssociation": "NONE"},
        {"number": 3, "body": BODY, "authorAssociation": "CONTRIBUTOR"},
    ]
    assert [i["number"] for i in doctor.runnable_issues(issues)] == [1]


def test_running_acceptance_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    args = doctor.build_parser().parse_args([])
    assert args.run_acceptance is False


def test_run_acceptance_reports_pass_and_fail(tmp_path: Path) -> None:
    issues = [
        {
            "number": 7,
            "title": "ok",
            "body": "## Acceptance\n```sh\ntrue\n```\n",
            "authorAssociation": "OWNER",
        },
        {
            "number": 8,
            "title": "bad",
            "body": "## Acceptance\n```sh\nfalse\n```\n",
            "authorAssociation": "OWNER",
        },
    ]
    results = doctor.run_acceptance(issues, cwd=tmp_path, timeout=30)
    assert results[7]["passed"] is True
    assert results[8]["passed"] is False


# ---- aggregation / exit code ----------------------------------------------


def test_exit_code_is_the_worst_level() -> None:
    mk = doctor.Finding
    assert doctor.exit_code([mk("a", "ok", "x"), mk("b", "ok", "y")]) == 0
    assert doctor.exit_code([mk("a", "ok", "x"), mk("b", "warn", "y")]) == 1
    assert doctor.exit_code([mk("a", "warn", "x"), mk("b", "block", "y")]) == 2


def test_report_is_machine_readable() -> None:
    report = doctor.render_json([doctor.Finding("git", "ok", "fine", ["d"])], now=NOW)
    data = json.loads(report)
    assert data["schema"] == "kg.doctor.v1"
    assert data["worst"] == "ok"
    assert data["findings"][0] == {
        "section": "git",
        "level": "ok",
        "summary": "fine",
        "detail": ["d"],
    }


# ---- collectors -----------------------------------------------------------


class _Done:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def test_ci_history_is_fetched_per_workflow_so_noise_cannot_crowd_it_out(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake(cmd: list[str], cwd: Path, timeout: int = 60) -> _Done:
        calls.append(cmd)
        if cmd[:3] == ["gh", "workflow", "list"]:
            return _Done(
                json.dumps(
                    [
                        {"name": "ops-suite", "state": "active"},
                        {"name": "agent-review", "state": "active"},
                        {"name": "retired", "state": "disabled_manually"},
                    ]
                )
            )
        name = cmd[cmd.index("--workflow") + 1]
        return _Done(
            json.dumps(
                [
                    _run("failure", 5, name),
                    _run("failure", 6, name),
                    _run("failure", 8, name),
                ]
            )
        )

    runs = doctor.collect_ci(tmp_path, run=fake)
    asked = [c[c.index("--workflow") + 1] for c in calls if "--workflow" in c]
    assert asked == ["ops-suite", "agent-review"]  # disabled workflows are skipped
    assert all(
        "--branch" in c and c[c.index("--branch") + 1] == "main"
        for c in calls
        if "--workflow" in c
    )
    assert {r["workflowName"] for r in runs} == {"ops-suite", "agent-review"}
    # and a three-day streak is now visible for each of them
    assert [f.level for f in doctor.evaluate_ci(runs, NOW)] == ["block", "block"]


def test_ci_collector_degrades_to_nothing_when_gh_is_unavailable(
    tmp_path: Path,
) -> None:
    assert doctor.collect_ci(tmp_path, run=lambda *a, **k: _Done("", 1)) == []


def test_production_probe_sends_a_user_agent_the_edge_accepts() -> None:
    request = doctor.prod_request()
    assert request.full_url.startswith("https://")
    assert request.get_header("User-agent") == "kg-doctor/1"
