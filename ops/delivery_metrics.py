"""Delivery speed, measured: how long a change takes from PR to main, and how often we release.

Pure functions over plain data plus two thin collectors (`gh pr list`, `git log`).
`doctor.py` renders the result as one finding so the trend is visible every week.

What is measured, and what is not:

* PR lead time = PR created -> merged.  It includes waiting for CI and for a human or
  agent, which is exactly what the requester experiences.
* Issue lead time = issue opened -> closed, for issues closed in the window: the time a
  requester waits for an answer, including everything before the PR exists.
* Release cadence = commits on main that bump the api version (`ops: release|prepare api
  X.Y.Z`).  ``origin/prod`` is only a pointer into main and keeps no history of when it
  moved, so this is a proxy and is labelled as such.
* Nothing here guesses post-release failure rates: there is no reliable source for them.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

WINDOW_DAYS = 28
TREND_DAYS = 14
MIN_TREND_SAMPLES = 3
LEAD_WARN_HOURS = 24.0
LEAD_P90_WARN_HOURS = 72.0
RELEASE_PATTERN = r"^ops: (release|prepare) api [0-9]+\.[0-9]+\.[0-9]+"
_VERSION = re.compile(r"api ([0-9]+\.[0-9]+\.[0-9]+)")


def _time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def lead_times(
    items: list[dict[str, Any]],
    now: datetime,
    days: float,
    end_key: str = "mergedAt",
) -> list[tuple[datetime, float]]:
    """(finished_at, hours from creation to finish) for items finished within the last `days`."""
    out = []
    for pr in items:
        if not pr.get(end_key) or not pr.get("createdAt"):
            continue
        merged, created = _time(pr[end_key]), _time(pr["createdAt"])
        if (now - merged).total_seconds() <= days * 86400 and merged >= created:
            out.append((merged, (merged - created).total_seconds() / 3600))
    return out


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def trend_percent(samples: list[tuple[datetime, float]], now: datetime) -> float | None:
    """Median lead time of the last TREND_DAYS vs the TREND_DAYS before; None if too thin."""
    recent = [h for t, h in samples if (now - t).total_seconds() <= TREND_DAYS * 86400]
    earlier = [h for t, h in samples if (now - t).total_seconds() > TREND_DAYS * 86400]
    if len(recent) < MIN_TREND_SAMPLES or len(earlier) < MIN_TREND_SAMPLES:
        return None
    base = statistics.median(earlier)
    return None if base == 0 else (statistics.median(recent) - base) / base * 100


def release_events(log: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """One (epoch, version) per released api version, earliest sighting, oldest first."""
    seen: dict[str, int] = {}
    for epoch, subject in log:
        match = _VERSION.search(subject)
        if match:
            version = match.group(1)
            seen[version] = min(epoch, seen.get(version, epoch))
    return sorted((epoch, version) for version, epoch in seen.items())


def summarize(
    prs: list[dict[str, Any]],
    releases: list[tuple[int, str]],
    now: datetime,
    issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    samples = lead_times(prs, now, WINDOW_DAYS)
    issue_hours = [h for _, h in lead_times(issues or [], now, WINDOW_DAYS, "closedAt")]
    hours = [h for _, h in samples]
    intervals = [(b[0] - a[0]) / 86400 for a, b in pairwise(releases)]
    summary: dict[str, Any] = {
        "merged": len(samples),
        "per_week": round(len(samples) / (WINDOW_DAYS / 7), 1),
        "median_h": round(statistics.median(hours), 1) if hours else None,
        "p90_h": round(percentile(hours, 90), 1) if hours else None,
        "trend_pct": trend_percent(samples, now),
        "issues_closed": len(issue_hours),
        "issue_median_h": round(statistics.median(issue_hours), 1)
        if issue_hours
        else None,
        "issue_p90_h": round(percentile(issue_hours, 90), 1) if issue_hours else None,
        "releases": len(releases),
        "release_median_days": round(statistics.median(intervals[-5:]), 1)
        if intervals
        else None,
        "days_since_release": (
            round((now.timestamp() - releases[-1][0]) / 86400, 1) if releases else None
        ),
    }
    return summary


def describe(summary: dict[str, Any]) -> str:
    if summary["merged"] == 0:
        lead = f"no PR merged in {WINDOW_DAYS}d"
    else:
        trend = summary["trend_pct"]
        arrow = "" if trend is None else f", trend {trend:+.0f}%"
        lead = (
            f"{summary['merged']} PRs/{WINDOW_DAYS}d ({summary['per_week']}/wk), lead time "
            f"median {summary['median_h']}h p90 {summary['p90_h']}h{arrow}"
        )
    if summary["issues_closed"]:
        lead += (
            f"; {summary['issues_closed']} issues closed, median {summary['issue_median_h']}h "
            f"p90 {summary['issue_p90_h']}h"
        )
    if summary["days_since_release"] is None:
        cadence = "no api release commits found"
    else:
        every = summary["release_median_days"]
        cadence = (
            f"last api release {summary['days_since_release']}d ago"
            + (f", median gap {every}d" if every is not None else "")
            + " (release commits on main; proxy)"
        )
    return f"{lead}; {cadence}"


def judge(summary: dict[str, Any]) -> tuple[str, list[str]]:
    problems = []
    if summary["median_h"] is not None and summary["median_h"] > LEAD_WARN_HOURS:
        problems.append(
            f"median lead time {summary['median_h']}h > {LEAD_WARN_HOURS:.0f}h"
        )
    if summary["p90_h"] is not None and summary["p90_h"] > LEAD_P90_WARN_HOURS:
        problems.append(
            f"p90 lead time {summary['p90_h']}h > {LEAD_P90_WARN_HOURS:.0f}h"
        )
    return ("warn" if problems else "ok"), problems


# --- collectors ---------------------------------------------------------------


def _gh_json(repo: Path, *argv: str) -> list[dict[str, Any]] | None:
    done = subprocess.run(
        ["gh", *argv], cwd=repo, capture_output=True, text=True, check=False
    )
    return json.loads(done.stdout) if not done.returncode and done.stdout else None


def collect(repo: Path) -> dict[str, Any] | None:
    prs = _gh_json(
        repo,
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        "200",
        "--json",
        "createdAt,mergedAt",
    )
    if prs is None:
        return None
    issues = _gh_json(
        repo,
        "issue",
        "list",
        "--state",
        "closed",
        "--limit",
        "200",
        "--json",
        "createdAt,closedAt",
    )
    log = subprocess.run(
        [
            "git",
            "log",
            "origin/main",
            "-E",
            f"--grep={RELEASE_PATTERN}",
            "--format=%ct\t%s",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    rows = []
    for line in log.stdout.splitlines() if not log.returncode else []:
        epoch, _, subject = line.partition("\t")
        if epoch.isdigit():
            rows.append((int(epoch), subject))
    return {"prs": prs, "issues": issues or [], "releases": release_events(rows)}
