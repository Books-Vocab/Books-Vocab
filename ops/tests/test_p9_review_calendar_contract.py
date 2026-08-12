"""P9 review-calendar cross-layer contracts.

These tests intentionally start as RED checks for the independent reviewer
block.  They stay narrow: source-level checks cover the compile/composition
seams, while the history check exercises the real generated fixture shape.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
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
    assert "uiWorldOrLive" in stats
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
    # At least one event must cross a UTC/local day boundary; an integer offset
    # assertion alone would not catch the production anchor geometry regression.
    assert any(
        datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00")).date()
        != datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00")).astimezone(zone).date()
        for event in history
    )


def test_generic_emitter_has_only_history_plan_clock_and_explicit_legacy_contract() -> None:
    emitter = _text(ROOT / "ops/demo/emit_ios.py")
    clock_module = _text(ROOT / "ops/review_calendar_clock.py")

    assert "clock_from_spec" not in emitter
    assert "clock_from_plan" in emitter
    assert "legacy" in clock_module.lower()
    assert "drift" in emitter


def test_generated_evidence_metadata_binds_actual_artifact_path_and_inode() -> None:
    ui_test = _text(IOS / "BooksAndVocabUITests/FixtureDatasetUITests.swift")

    assert "GeneratedEvidence" in ui_test
    assert "artifactPath" in ui_test
    assert "fileNumber" in ui_test
    assert "assetInodes" in ui_test
    assert "p9_review_calendar_evidence.json" in ui_test


def test_overview_page_requires_exactly_one_selector_match() -> None:
    source = _text(IOS / "BooksAndVocabUITests/Pages/OverviewPage.swift")

    assert ".firstMatch" not in source
    assert "query.count" in source
    assert "element(boundBy: 0)" in source
