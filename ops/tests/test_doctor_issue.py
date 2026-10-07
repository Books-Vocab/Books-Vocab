from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import doctor
import doctor_issue


def report(*findings: tuple[str, str, str], at: str = "2026-10-07T03:23:00Z") -> dict:
    items = [
        {"section": section, "level": level, "summary": summary, "detail": []}
        for section, level, summary in findings
    ]
    worst = max(
        (f["level"] for f in items), key=["ok", "warn", "block"].index, default="ok"
    )
    return {"generated_at": at, "worst": worst, "findings": items}


# ---- the decision ---------------------------------------------------------------


def test_all_ok_with_no_open_issue_does_nothing() -> None:
    assert doctor_issue.plan(report(("ci", "ok", "fine")), None)["action"] == "noop"


def test_all_ok_closes_an_open_report_with_a_comment() -> None:
    decision = doctor_issue.plan(
        report(("ci", "ok", "fine")), {"number": 7, "body": "x"}
    )
    assert decision["action"] == "close"
    assert decision["number"] == 7
    assert "2026-10-07" in decision["comment"]


def test_a_new_finding_creates_the_issue_with_label_title_and_only_non_ok_findings() -> (
    None
):
    decision = doctor_issue.plan(
        report(("ci", "ok", "fine"), ("release", "warn", "prod trails main by 300")),
        None,
    )
    assert decision["action"] == "create"
    assert decision["title"] == doctor_issue.TITLE
    assert "release" in decision["body"]
    assert "prod trails main by 300" in decision["body"]
    assert "fine" not in decision["body"]


def test_unchanged_findings_do_not_touch_the_issue_even_when_the_timestamp_moves() -> (
    None
):
    first = report(
        ("release", "warn", "prod trails main by 300"), at="2026-10-01T00:00:00Z"
    )
    existing = {"number": 7, "body": doctor_issue.render_body(first)}
    later = report(
        ("release", "warn", "prod trails main by 300"), at="2026-10-08T00:00:00Z"
    )
    assert doctor_issue.plan(later, existing)["action"] == "noop"


def test_changed_findings_update_the_same_issue() -> None:
    first = report(("release", "warn", "prod trails main by 300"))
    existing = {"number": 7, "body": doctor_issue.render_body(first)}
    changed = report(("release", "block", "prod trails main by 1200"))
    decision = doctor_issue.plan(changed, existing)
    assert decision["action"] == "update"
    assert decision["number"] == 7
    assert "1200" in decision["body"]


def test_details_are_listed_under_their_finding() -> None:
    rep = report(("ci", "warn", "known red"))
    rep["findings"][0]["detail"] = ["ops-suite red for 5 days"]
    assert "  - ops-suite red for 5 days" in doctor_issue.render_body(rep)


# ---- the gh edge ------------------------------------------------------------------


def test_create_makes_sure_the_label_exists_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        doctor_issue, "gh", lambda *a, stdin=None: calls.append(a) or ""
    )
    doctor_issue.apply({"action": "create", "title": "t", "body": "b"}, "o/r")
    assert [c[0:2] for c in calls] == [("label", "create"), ("issue", "create")]
    assert "--force" in calls[0]


def test_noop_never_calls_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor_issue, "gh", lambda *a, **k: pytest.fail("gh called"))
    doctor_issue.apply({"action": "noop", "reason": "x"}, None)


def test_main_dry_run_prints_the_decision_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report(("ci", "warn", "red"))))
    monkeypatch.setattr(doctor_issue, "find_open_issue", lambda repo: None)
    monkeypatch.setattr(
        doctor_issue, "apply", lambda *a: pytest.fail("wrote in dry-run")
    )
    assert doctor_issue.main([str(path), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "create"


# ---- doctor stays out of its own report ---------------------------------------------


def test_doctor_ignores_the_health_report_issue_in_its_own_accounting() -> None:
    issues = [
        {"number": 1, "labels": [{"name": "health-report"}]},
        {"number": 2, "labels": [{"name": "bug"}]},
        {"number": 3, "labels": []},
    ]
    assert [i["number"] for i in doctor.exclude_health_report(issues)] == [2, 3]
