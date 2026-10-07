#!/usr/bin/env -S uv run --python 3.13 python
"""Read-only project health: one report that answers "is the loop still closed?".

It aggregates what other tools already know and adds only the judgements none of
them make: a CI check that has stayed red on main (known-red), how far production
trails main, claims whose worktree is gone, and whether open issues can be
verified by their own acceptance commands.

Nothing here writes to the repository, the registry or GitHub.  Issue acceptance
commands are *reported* by default; ``--run-acceptance`` executes them, and only
for issues authored by the repository owner (issue text is data, anyone can file
one), one at a time, with a timeout.

Exit code: 0 all ok, 1 warnings, 2 at least one blocker.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "kg.doctor.v1"

# A check that stays red on main this long is normalised deviance, not noise.
KNOWN_RED_MIN_STREAK = 3
KNOWN_RED_MIN_DAYS = 3
# Production that trails main this far (or this old) accumulates unbounded risk.
RELEASE_GAP_WARN_COMMITS = 200
RELEASE_GAP_BLOCK_COMMITS = 1000
RELEASE_GAP_WARN_DAYS = 14
RELEASE_GAP_BLOCK_DAYS = 45
PROD_INFO_URL = "https://wordnexus.lol/api/system/info"
DISK_GUARD_FILE = (
    Path.home() / "Library" / "Application Support" / "KG" / "disk_guard.json"
)
_REAL_CONCLUSIONS = {"success", "failure", "timed_out", "startup_failure"}
_LIVE_CLAIM_STATUSES = {"active", "published", "cleanup_pending"}
_ORDER = {"ok": 0, "warn": 1, "block": 2}


@dataclass(frozen=True)
class Finding:
    section: str
    level: str
    summary: str
    detail: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Pure evaluators (everything below is unit-tested without any I/O)
# --------------------------------------------------------------------------


def evaluate_git(facts: dict[str, Any]) -> Finding:
    problems = []
    if facts.get("branch") != "main":
        problems.append(f"checkout is on {facts.get('branch')!r}, not main")
    if facts.get("dirty"):
        problems.append(f"{facts['dirty']} uncommitted path(s)")
    if facts.get("local") != facts.get("origin"):
        problems.append(
            "local main differs from origin/main (run delivery.py sync-main)"
        )
    if problems:
        return Finding("git", "warn", "canonical checkout needs attention", problems)
    return Finding("git", "ok", "canonical checkout is clean main == origin/main")


def evaluate_registry(records: list[dict[str, Any]]) -> Finding:
    live = [r for r in records if r.get("status") in _LIVE_CLAIM_STATUSES]
    detail = []
    for record in live:
        label = f"{record.get('branch')} [{record.get('status')}]"
        if not os.path.exists(str(record.get("path", ""))):
            detail.append(f"ghost claim (worktree path gone): {label}")
        if record.get("status") == "active" and not record.get("codex_thread_id"):
            detail.append(f"ownerless active claim: {label}")
    if detail:
        return Finding(
            "registry",
            "warn",
            f"{len(live)} live claim(s), {len(detail)} problem(s)",
            detail,
        )
    return Finding("registry", "ok", f"{len(live)} live claim(s), none stale")


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def evaluate_ci(runs: list[dict[str, Any]], now: datetime) -> list[Finding]:
    """Judge each workflow by how long it has been failing on main."""

    by_workflow: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        if run.get("conclusion") in _REAL_CONCLUSIONS:
            by_workflow.setdefault(str(run.get("workflowName")), []).append(run)
    findings = []
    for name, items in sorted(by_workflow.items()):
        items.sort(key=lambda r: r["createdAt"], reverse=True)
        streak = []
        for run in items:
            if run["conclusion"] == "success":
                break
            streak.append(run)
        if len(streak) >= KNOWN_RED_MIN_STREAK:
            age = (now - _parse_time(streak[-1]["createdAt"])).total_seconds() / 86400
            if age >= KNOWN_RED_MIN_DAYS:
                findings.append(
                    Finding(
                        "ci",
                        "block",
                        f"{name} known-red: {len(streak)} consecutive failures on main over {age:.0f} days",
                        [
                            "fix it or demote it; a check nobody acts on trains everyone to ignore red"
                        ],
                    )
                )
                continue
        findings.append(
            Finding(
                "ci", "ok", f"{name} not known-red ({len(streak)} recent failure(s))"
            )
        )
    return findings or [
        Finding("ci", "warn", "no finished workflow runs found on main")
    ]


def evaluate_release_gap(
    sha: str | None, behind: int | None, age_days: float | None
) -> Finding:
    if not sha or behind is None or age_days is None:
        return Finding(
            "release",
            "warn",
            "production version unknown (cannot measure the gap to main)",
        )
    summary = f"production {sha[:9]} trails main by {behind} commit(s), {age_days:.0f} day(s) old"
    if behind >= RELEASE_GAP_BLOCK_COMMITS or age_days >= RELEASE_GAP_BLOCK_DAYS:
        return Finding(
            "release",
            "block",
            summary,
            ["unreleased risk grows with every merge; ship smaller, more often"],
        )
    if behind >= RELEASE_GAP_WARN_COMMITS or age_days >= RELEASE_GAP_WARN_DAYS:
        return Finding("release", "warn", summary)
    return Finding("release", "ok", summary)


def evaluate_disk(guard: dict[str, Any] | None) -> Finding:
    if not guard:
        return Finding("disk", "ok", "no disk guard state on this machine")
    verdict = str(guard.get("verdict"))
    level = {"ok": "ok", "warning": "warn", "block": "block"}.get(verdict, "warn")
    return Finding("disk", level, f"disk guard {verdict}: {guard.get('reason')}")


def evaluate_complexity(
    rows: list[dict[str, Any]] | None, ops_to_ios: float | None
) -> Finding:
    if rows is None:
        return Finding(
            "complexity",
            "warn",
            "complexity budget unreadable (ops/complexity_budget.json)",
        )
    over = [r for r in rows if r["over"]]
    ratio = f", ops:ios {ops_to_ios}" if ops_to_ios is not None else ""
    if over:
        return Finding(
            "complexity",
            "warn",
            f"{len(over)} area(s) over their line budget{ratio}",
            [
                f"{r['area']}: {r['lines']:,} lines > ceiling {r['ceiling']:,}"
                for r in over
            ],
        )
    tight = min(rows, key=lambda r: r["headroom"])
    return Finding(
        "complexity",
        "ok",
        f"within budget; tightest is {tight['area']} ({tight['headroom']:,} lines headroom){ratio}",
    )


def parse_acceptance(body: str | None) -> list[str]:
    """Shell commands in fenced blocks under the issue's ``## Acceptance`` heading."""

    if not body:
        return []
    section = re.search(
        r"^##\s+Acceptance\s*$(.*?)(?=^##\s|\Z)", body, re.MULTILINE | re.DOTALL
    )
    if not section:
        return []
    return [
        block.strip()
        for block in re.findall(
            r"```(?:sh|bash|shell)\n(.*?)```", section.group(1), re.DOTALL
        )
        if block.strip()
    ]


def runnable_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only owner-authored issues may have their acceptance text executed."""

    return [
        i
        for i in issues
        if i.get("authorAssociation") == "OWNER" and parse_acceptance(i.get("body"))
    ]


def evaluate_issues(
    issues: list[dict[str, Any]], results: dict[int, dict[str, Any]] | None = None
) -> Finding:
    detail = []
    level = "ok"
    unverifiable = []
    for issue in issues:
        number = issue["number"]
        if not parse_acceptance(issue.get("body")):
            unverifiable.append(f"#{number} has no machine acceptance command")
            continue
        if results and number in results:
            outcome = results[number]
            if outcome["passed"]:
                detail.append(f"#{number} acceptance PASSES on this checkout: close it")
                level = max(level, "warn", key=_ORDER.get)
            else:
                detail.append(f"#{number} acceptance not yet met ({outcome['reason']})")
    detail.extend(unverifiable)
    if unverifiable:
        level = max(level, "warn", key=_ORDER.get)
    return Finding(
        "issues",
        level,
        f"{len(issues)} open issue(s), {len(unverifiable)} without a machine acceptance command",
        detail,
    )


def run_acceptance(
    issues: list[dict[str, Any]], *, cwd: Path, timeout: int = 300
) -> dict[int, dict[str, Any]]:
    results: dict[int, dict[str, Any]] = {}
    for issue in runnable_issues(issues):
        passed, reason = True, "all commands exited 0"
        for command in parse_acceptance(issue["body"]):
            try:
                done = subprocess.run(
                    ["bash", "-c", command],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                passed, reason = False, f"timed out after {timeout}s"
                break
            if done.returncode != 0:
                passed, reason = False, f"exit {done.returncode}"
                break
        results[issue["number"]] = {"passed": passed, "reason": reason}
    return results


def exit_code(findings: list[Finding]) -> int:
    return max((_ORDER[f.level] for f in findings), default=0)


def render_json(findings: list[Finding], *, now: datetime) -> str:
    worst = max((f.level for f in findings), key=_ORDER.get, default="ok")
    return json.dumps(
        {
            "schema": SCHEMA,
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "worst": worst,
            "findings": [asdict(f) for f in findings],
        },
        indent=2,
        ensure_ascii=False,
    )


def render_text(findings: list[Finding]) -> str:
    mark = {"ok": "ok   ", "warn": "WARN ", "block": "BLOCK"}
    lines = []
    for f in findings:
        lines.append(f"[{mark[f.level]}] {f.section:9} {f.summary}")
        lines.extend(f"            - {d}" for d in f.detail)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Collectors (thin; each turns an existing tool's output into plain data)
# --------------------------------------------------------------------------


def _run(
    cmd: list[str], cwd: Path, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def collect_git(repo: Path) -> dict[str, Any]:
    def out(*args: str) -> str:
        return _run(["git", *args], repo).stdout.strip()

    return {
        "branch": out("branch", "--show-current"),
        "dirty": len(
            [line for line in out("status", "--porcelain").splitlines() if line]
        ),
        "local": out("rev-parse", "main"),
        "origin": out("rev-parse", "origin/main"),
    }


def collect_registry(repo: Path) -> list[dict[str, Any]]:
    done = _run([str(repo / "ops" / "worktree_orchestrate.py"), "list", "--json"], repo)
    return (
        json.loads(done.stdout).get("records", [])
        if done.returncode == 0 and done.stdout
        else []
    )


def collect_ci(repo: Path, run: Any = _run) -> list[dict[str, Any]]:
    """Recent main runs of every active workflow, each with its *own* history.

    One shared ``--limit`` is useless: a noisy workflow (agent-review fires on every
    PR event) fills the window and leaves hours of history for the others, so a
    three-day streak could never be seen.
    """

    listing = run(["gh", "workflow", "list", "--json", "name,state"], repo)
    if listing.returncode or not listing.stdout:
        return []
    runs: list[dict[str, Any]] = []
    for workflow in json.loads(listing.stdout):
        if workflow.get("state") != "active":
            continue
        done = run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow["name"],
                "--branch",
                "main",
                "--limit",
                "40",
                "--json",
                "workflowName,conclusion,status,createdAt",
            ],
            repo,
        )
        if not done.returncode and done.stdout:
            runs.extend(json.loads(done.stdout))
    return runs


def prod_request() -> urllib.request.Request:
    # The edge rejects Python's default User-Agent with 403, so identify ourselves.
    return urllib.request.Request(PROD_INFO_URL, headers={"User-Agent": "kg-doctor/1"})


def collect_release_gap(
    repo: Path, now: datetime
) -> tuple[str | None, int | None, float | None]:
    try:
        with urllib.request.urlopen(prod_request(), timeout=10) as response:
            sha = json.load(response).get("version")
    except (OSError, ValueError):
        return None, None, None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return None, None, None
    behind = _run(["git", "rev-list", "--count", f"{sha}..origin/main"], repo)
    stamp = _run(["git", "log", "-1", "--format=%ct", sha], repo)
    if behind.returncode or stamp.returncode or not stamp.stdout.strip():
        return sha, None, None
    age = (now.timestamp() - int(stamp.stdout.strip())) / 86400
    return sha, int(behind.stdout.strip()), age


def collect_complexity(repo: Path) -> tuple[list[dict[str, Any]] | None, float | None]:
    import complexity

    try:
        measured = complexity.measure(repo)
        budget = complexity.load_budget(repo / complexity.BUDGET_FILE)
    except (complexity.BudgetError, subprocess.CalledProcessError):
        return None, None
    return complexity.evaluate(measured, budget), complexity.ratio(measured)


def collect_disk() -> dict[str, Any] | None:
    try:
        return json.loads(DISK_GUARD_FILE.read_text())
    except (OSError, ValueError):
        return None


def collect_issues(repo: Path) -> list[dict[str, Any]]:
    done = _run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,title,body,authorAssociation,labels",
        ],
        repo,
    )
    issues = json.loads(done.stdout) if done.returncode == 0 and done.stdout else []
    return exclude_health_report(issues)


HEALTH_LABEL = "health-report"


def exclude_health_report(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The weekly report is this tool's own output; counting it would make it self-referential."""
    return [
        issue
        for issue in issues
        if HEALTH_LABEL not in {label.get("name") for label in issue.get("labels", [])}
    ]


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only project health report.")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="skip checks that only exist on a developer machine (checkout state, claims, disk guard)",
    )
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--json", action="store_true", help="machine-readable report on stdout"
    )
    parser.add_argument(
        "--run-acceptance",
        action="store_true",
        help="execute the acceptance commands of owner-authored open issues on this checkout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = args.repo.resolve()
    now = datetime.now(timezone.utc)
    git = None if args.ci and not args.run_acceptance else collect_git(repo)
    issues = collect_issues(repo)
    results = None
    if args.run_acceptance:
        if git["branch"] != "main" or git["dirty"] or git["local"] != git["origin"]:
            print(
                "doctor: --run-acceptance needs a clean main == origin/main checkout",
                file=sys.stderr,
            )
            return 2
        print(
            "doctor: running acceptance commands of owner-authored issues",
            file=sys.stderr,
        )
        results = run_acceptance(issues, cwd=repo)
    ci = evaluate_ci(collect_ci(repo), now)
    gap = evaluate_release_gap(*collect_release_gap(repo, now))
    complexity_finding = evaluate_complexity(*collect_complexity(repo))
    issues_finding = evaluate_issues(issues, results)
    if args.ci:
        findings = [*ci, gap, complexity_finding, issues_finding]
    else:
        findings = [
            evaluate_git(git),
            evaluate_registry(collect_registry(repo)),
            *ci,
            gap,
            evaluate_disk(collect_disk()),
            complexity_finding,
            issues_finding,
        ]
    print(render_json(findings, now=now) if args.json else render_text(findings))
    return exit_code(findings)


if __name__ == "__main__":
    sys.exit(main())
