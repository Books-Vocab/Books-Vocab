from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import delivery_metrics as dm
import doctor

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def stamp(delta: timedelta) -> str:
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(merged_days_ago: float, hours: float) -> dict:
    merged = timedelta(days=merged_days_ago)
    return {
        "createdAt": stamp(merged + timedelta(hours=hours)),
        "mergedAt": stamp(merged),
    }


# ---- lead times ----------------------------------------------------------------


def test_lead_time_is_creation_to_merge_in_hours_within_the_window() -> None:
    samples = dm.lead_times([pr(1, 2.0), pr(40, 5.0)], NOW, 28)
    assert [round(h, 2) for _, h in samples] == [2.0]


def test_unmerged_and_impossible_records_are_ignored() -> None:
    items = [
        {"createdAt": stamp(timedelta(days=2)), "mergedAt": None},
        {"createdAt": stamp(timedelta(days=1)), "mergedAt": stamp(timedelta(days=2))},
        {"mergedAt": stamp(timedelta(days=1))},
    ]
    assert dm.lead_times(items, NOW, 28) == []


def test_issue_lead_time_reads_closed_at() -> None:
    issues = [
        {"createdAt": stamp(timedelta(days=3)), "closedAt": stamp(timedelta(days=1))}
    ]
    [(_, hours)] = dm.lead_times(issues, NOW, 28, "closedAt")
    assert hours == pytest.approx(48.0)


def test_percentile_is_the_nearest_rank_and_safe_on_one_value() -> None:
    values = [float(n) for n in range(1, 11)]
    assert dm.percentile(values, 90) == 9.0
    assert dm.percentile(values, 50) == 5.0
    assert dm.percentile([7.0], 90) == 7.0


# ---- trend ---------------------------------------------------------------------


def test_trend_compares_the_last_two_weeks_with_the_two_before() -> None:
    samples = [(NOW - timedelta(days=d), 10.0) for d in (20, 21, 22)] + [
        (NOW - timedelta(days=d), 5.0) for d in (1, 2, 3)
    ]
    assert dm.trend_percent(samples, NOW) == pytest.approx(-50.0)


def test_trend_is_withheld_when_either_side_is_thin() -> None:
    thin = [(NOW - timedelta(days=d), 5.0) for d in (1, 2)] + [
        (NOW - timedelta(days=20), 5.0)
    ] * 3
    assert dm.trend_percent(thin, NOW) is None


# ---- releases ------------------------------------------------------------------


def test_release_events_dedupe_by_version_keeping_the_earliest_sighting() -> None:
    log = [
        (300, "ops: prepare api 2.0.4"),
        (100, "ops: release api 2.0.3"),
        (250, "ops: prepare api 2.0.4"),
        (50, "unrelated commit"),
    ]
    assert dm.release_events(log) == [(100, "2.0.3"), (250, "2.0.4")]


# ---- summary and verdict -------------------------------------------------------


def test_summary_reports_counts_rate_and_percentiles() -> None:
    prs = [pr(1, h) for h in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    summary = dm.summarize(prs, [], NOW)
    assert summary["merged"] == 10
    assert summary["per_week"] == 2.5
    assert summary["median_h"] == 5.5
    assert summary["p90_h"] == 9.0
    assert summary["days_since_release"] is None


def test_release_cadence_uses_the_recent_gaps_and_days_since_the_last() -> None:
    day = 86400
    start = int(NOW.timestamp()) - 40 * day
    releases = [(start, "1"), (start + 10 * day, "2"), (start + 30 * day, "3")]
    summary = dm.summarize([], releases, NOW)
    assert summary["release_median_days"] == 15.0
    assert summary["days_since_release"] == 10.0


def test_fast_delivery_is_ok_and_slow_delivery_names_the_problem() -> None:
    fast = dm.summarize([pr(1, 0.2) for _ in range(5)], [], NOW)
    assert dm.judge(fast) == ("ok", [])
    slow = dm.summarize([pr(1, 30.0) for _ in range(5)] + [pr(2, 100.0)], [], NOW)
    level, problems = dm.judge(slow)
    assert level == "warn"
    assert any("median" in p for p in problems) or any("p90" in p for p in problems)


def test_the_description_says_the_release_numbers_are_a_proxy() -> None:
    text = dm.describe(
        dm.summarize([pr(1, 1.0)], [(int(NOW.timestamp()) - 86400, "2.0.4")], NOW)
    )
    assert "proxy" in text
    assert "lead time median 1.0h" in text


def test_an_empty_window_is_described_not_crashed_on() -> None:
    summary = dm.summarize([], [], NOW)
    assert "no PR merged" in dm.describe(summary)
    assert dm.judge(summary) == ("ok", [])


def test_closed_issues_appear_in_the_description_when_there_are_some() -> None:
    issues = [
        {"createdAt": stamp(timedelta(days=3)), "closedAt": stamp(timedelta(days=1))}
    ]
    text = dm.describe(dm.summarize([pr(1, 1.0)], [], NOW, issues))
    assert "1 issues closed, median 48.0h" in text


# ---- collectors and doctor -------------------------------------------------------


def test_a_failed_gh_call_yields_none_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom")
    )
    assert dm.collect(Path(".")) is None


def test_doctor_warns_when_metrics_are_unavailable() -> None:
    assert doctor.evaluate_delivery(None, NOW).level == "warn"


def test_doctor_reports_the_numbers_for_healthy_delivery() -> None:
    data = {"prs": [pr(1, 0.3) for _ in range(4)], "issues": [], "releases": []}
    finding = doctor.evaluate_delivery(data, NOW)
    assert finding.section == "delivery"
    assert finding.level == "ok"
    assert "4 PRs/28d" in finding.summary


# ---- review findings on the first version -----------------------------------------


def test_percentile_uses_the_ceiling_so_one_outlier_in_five_is_the_p90() -> None:
    assert dm.percentile([1.0, 1.0, 1.0, 1.0, 100.0], 90) == 100.0
    assert dm.percentile([1.0, 2.0], 50) == 1.0


def test_an_outlier_reaches_the_p90_warning() -> None:
    summary = dm.summarize([pr(1, h) for h in (1, 1, 1, 1, 200)], [], NOW)
    level, problems = dm.judge(summary)
    assert level == "warn"
    assert any("p90" in p for p in problems)


def _fake_run(responses: dict[str, tuple[int, str]]):
    calls: list[list[str]] = []

    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        key = (
            "gh-pr"
            if cmd[:3] == ["gh", "pr", "list"]
            else "gh-issue"
            if cmd[:3] == ["gh", "issue", "list"]
            else "git"
        )
        code, out = responses[key]
        return subprocess.CompletedProcess(cmd, code, out, "")

    return run, calls


GOOD = {"gh-pr": (0, "[]"), "gh-issue": (0, "[]"), "git": (0, "")}


@pytest.mark.parametrize("broken", ["gh-pr", "gh-issue", "git"])
def test_any_failed_source_makes_the_whole_collection_unavailable(
    monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    run, _ = _fake_run({**GOOD, broken: (1, "")})
    monkeypatch.setattr(subprocess, "run", run)
    assert dm.collect(Path("."), NOW) is None


def test_collection_asks_github_for_the_whole_window_not_a_fixed_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, calls = _fake_run(GOOD)
    monkeypatch.setattr(subprocess, "run", run)
    data = dm.collect(Path("."), NOW)
    assert data is not None
    assert data["truncated"] is False
    pr_call = next(c for c in calls if c[:3] == ["gh", "pr", "list"])
    assert pr_call[pr_call.index("--search") + 1] == "merged:>=2026-09-09"
    assert pr_call[pr_call.index("--limit") + 1] == str(dm.FETCH_LIMIT)


def test_hitting_the_fetch_cap_is_flagged_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full = "[" + ",".join(["{}"] * dm.FETCH_LIMIT) + "]"
    run, _ = _fake_run({**GOOD, "gh-pr": (0, full)})
    monkeypatch.setattr(subprocess, "run", run)
    data = dm.collect(Path("."), NOW)
    assert data is not None and data["truncated"] is True
    finding = doctor.evaluate_delivery({**data, "prs": [], "releases": []}, NOW)
    assert "lower bound" in finding.summary
    assert finding.level == "warn"
