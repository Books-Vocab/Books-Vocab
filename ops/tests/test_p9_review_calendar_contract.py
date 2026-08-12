"""P9 review-calendar cross-layer contracts.

These tests intentionally start as RED checks for the independent reviewer
block.  They stay narrow: source-level checks cover the compile/composition
seams, while the history check exercises the real generated fixture shape.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.demo.ui_world_seed import shape_history
from ops.review_calendar_clock import clock_from_plan

IOS = ROOT / "ios"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_catalog_fixed_month_binds_the_calendar_date_without_undefined_symbol() -> None:
    source = _text(IOS / "BooksAndVocab/Debug/Scenarios/VocabCalendarGridScenarios.swift")

    assert "calendar.date(from: comps) ?? month" not in source
    assert re.search(
        r"private static func fixedMonth\(\) -> Date \{.*?"
        r"guard let month = calendar\.date\(from: comps\)",
        source,
        re.DOTALL,
    )


def test_ui_calendar_uses_the_canonical_dense_seed_and_proves_clock_provenance() -> None:
    launch_source = _text(IOS / "BooksAndVocabUITests/Helpers/UITestAppLaunch.swift")
    seed_source = _text(IOS / "BooksAndVocab/Support/UITestFixtureSeed.swift")
    seed_files = "\n".join(
        _text(path)
        for path in (IOS / "BooksAndVocab/Support").glob("UITestFixtureSeed*.swift")
    )
    ui_test = _text(IOS / "BooksAndVocabUITests/FixtureDatasetUITests.swift")

    assert "case reviewCalendarDense" in launch_source
    assert "-seedFixture:vocabulary:reviewCalendarDense" in launch_source
    assert 'case "vocabulary"' in seed_source
    assert "FixtureDatasetStore.requireVocabularySeed(for: .reviewCalendarDense)" in seed_files
    assert ui_test.count("fixtures: [.reviewCalendarDense]") == 2
    assert "fixtures: [.shellNavigation]" not in ui_test
    assert "reviewCalendar.clock.history_plan.anchor_day" in ui_test
    assert "reviewCalendar.clock.live" in ui_test
    assert re.search(
        r"XCTAssertEqual\(\s*canonical\.count,\s*1.*?"
        r"XCTAssertEqual\(\s*live\.count,\s*0",
        ui_test,
        re.DOTALL,
    )


def test_ui_world_production_composition_has_one_fixture_clock_boundary() -> None:
    clock = _text(IOS / "BooksAndVocab/Views/Vocabulary/Scenes/ReviewCalendarPresenter.swift")
    stats = _text(IOS / "BooksAndVocab/Views/Vocabulary/Scenes/StatsPresenter.swift")
    overview = _text(IOS / "BooksAndVocab/Views/Vocabulary/Scenes/OverviewTab.swift")

    assert "FixtureDatasetStore.scenarioContext()" in clock
    assert "uiWorldOrLive" in clock
    assert "ReviewCalendarAccessibility.clock" in clock
    assert "reviewClock" in stats
    assert "ReviewCalendarClock.live(settings: reviewSettingsStore.settings)" not in stats
    assert "reviewClock: ReviewCalendarClock.uiWorldOrLive" in overview
    assert "Date()" not in clock.split("static func uiWorldOrLive", 1)[-1].split("var startOfToday", 1)[0]


def test_history_plan_geometry_matches_production_timezone_and_real_day_buckets() -> None:
    plan = _json(ROOT / "ops/demo/ui_world_seed/history_plan.json")
    anchor = date.fromisoformat(plan["anchor_day"])
    zone = ZoneInfo(plan["review_clock_time_zone"])
    probe = datetime.combine(anchor, datetime.min.time(), tzinfo=zone)
    production_offset = int(probe.utcoffset().total_seconds() // 3600)

    assert plan["render_utc_offset_hours"] == [production_offset]

    lo, hi = plan["event_utc_hours"]
    assert lo >= max(0, -production_offset)
    assert hi <= min(23, 23 - production_offset)

    fixture = _json(ROOT / "ops/fixtures/ui_worlds/marketing_demo.json")
    history = fixture["vocabulary"]["reviewCalendarDense"]["reviewHistory"]
    buckets: dict[str, int] = {}
    for event in history:
        instant = datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00"))
        key = instant.astimezone(zone).date().isoformat()
        buckets[key] = buckets.get(key, 0) + 1

    assert buckets.get(anchor.isoformat(), 0) > 0
    # The [10,23] UTC window is the exact same-local-day intersection for the
    # production -10 offset. A UTC/local date boundary is proved by the
    # dedicated screenshot evidence contract, not fabricated in review data.
    assert all(
        datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00")).date()
        == datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00")).astimezone(zone).date()
        for event in history
    )


def test_canonical_producer_keeps_source_plan_and_both_committed_artifacts_in_lockstep() -> None:
    """The plan and shaped spec, not a stale JSON snapshot, own P9 geometry."""
    plan = _json(ROOT / "ops/demo/ui_world_seed/history_plan.json")
    spec = _json(ROOT / "ops/demo/ui_world_seed/scenario_account_spec.json")
    shaped_report = shape_history.narrative_report(spec, plan)
    expected_clock = clock_from_plan(plan)
    expected_current = int(plan["current_streak_days"])
    expected_longest = int(plan["longest_streak_days"])
    expected_primary_due = int(plan["due_at_anchor"]["primary"])
    expected_other_due = int(plan["due_at_anchor"]["other"])
    assert shaped_report["currentStreak"] == expected_current
    assert shaped_report["longestStreak"] == expected_longest
    assert shaped_report["duePrimary"] == expected_primary_due
    assert shaped_report["dueOther"] == expected_other_due
    assert shaped_report["horizonViolations"] == []
    assert shaped_report["forbiddenDayEvents"] == []

    lo, hi = (int(value) for value in plan["event_utc_hours"])
    zone = ZoneInfo(str(plan["review_clock_time_zone"]))
    anchor = date.fromisoformat(str(plan["anchor_day"]))

    def artifact_geometry(path: Path) -> tuple[int, int, int, list[str]]:
        fixture = _json(path)
        assert fixture["scenarioContext"]["reviewClock"] == expected_clock
        dense = fixture["vocabulary"]["reviewCalendarDense"]
        history = dense["reviewHistory"]
        assert history
        event_hours: list[int] = []
        day_counts: dict[str, int] = {}
        for event in history:
            instant = datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00"))
            event_hours.append(instant.hour)
            local_day = instant.astimezone(zone).date().isoformat()
            day_counts[local_day] = day_counts.get(local_day, 0) + 1
        assert all(lo <= hour <= hi for hour in event_hours), (
            f"{path}: reviewHistory UTC hours escaped history_plan window "
            f"[{lo},{hi}]: {sorted(set(event_hours))}"
        )
        current = 0
        cursor = anchor
        while day_counts.get(cursor.isoformat(), 0) > 0:
            current += 1
            cursor -= timedelta(days=1)
        sorted_days = sorted(day_counts)
        longest = run = 0
        if sorted_days:
            cursor = date.fromisoformat(sorted_days[0])
            last = date.fromisoformat(sorted_days[-1])
            while cursor <= last:
                if day_counts.get(cursor.isoformat(), 0) > 0:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
                cursor += timedelta(days=1)
        due = 0
        for entry in dense["entries"]:
            next_review = entry.get("nextReviewAt")
            if not next_review:
                continue
            next_day = datetime.fromisoformat(next_review.replace("Z", "+00:00"))
            if next_day.astimezone(zone).date() <= anchor:
                due += 1
        return current, longest, due, event_hours

    generated_geometry = artifact_geometry(
        ROOT / "ops/demo/generated/ios_fixture_dataset.json"
    )
    marketing_geometry = artifact_geometry(
        ROOT / "ops/fixtures/ui_worlds/marketing_demo.json"
    )
    assert generated_geometry[:3] == (
        expected_current,
        expected_longest,
        expected_primary_due,
    )
    assert marketing_geometry[:3] == generated_geometry[:3]
    generated_dense = _json(
        ROOT / "ops/demo/generated/ios_fixture_dataset.json"
    )["vocabulary"]["reviewCalendarDense"]
    marketing_dense = _json(
        ROOT / "ops/fixtures/ui_worlds/marketing_demo.json"
    )["vocabulary"]["reviewCalendarDense"]
    assert generated_dense == marketing_dense


def test_generic_emitter_has_only_history_plan_clock_and_explicit_legacy_contract() -> None:
    emitter = _text(ROOT / "ops/demo/emit_ios.py")
    clock_module = _text(ROOT / "ops/review_calendar_clock.py")

    assert "clock_from_spec" not in emitter
    assert "clock_from_plan" in emitter
    assert "legacy" in clock_module.lower()
    assert "drift" in emitter


def test_generated_evidence_metadata_uses_portable_v2_provenance() -> None:
    ui_test = _text(IOS / "BooksAndVocabUITests/FixtureDatasetUITests.swift")

    assert "GeneratedEvidence" in ui_test
    assert "artifactPath" in ui_test
    assert "bytes" in ui_test
    assert "sha256" in ui_test
    assert "selector" in ui_test
    assert "source" in ui_test
    assert "datasetID" in ui_test
    assert "device" in ui_test
    assert "installedFixture" in ui_test
    assert "inode" not in ui_test


def test_overview_page_requires_exactly_one_selector_match() -> None:
    source = _text(IOS / "BooksAndVocabUITests/Pages/OverviewPage.swift")

    assert ".firstMatch" not in source
    assert "query.count" in source
    assert "element(boundBy: 0)" in source
