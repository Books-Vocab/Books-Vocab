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
from ops.p9_review_calendar_evidence import (
    EVIDENCE_SCHEMA,
    make_record,
    validate_manifest_file,
)
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
    boundary = plan["review_calendar_boundary_event"]
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
    # production -10 offset. One explicit plan-owned event crosses the
    # boundary so the UI evidence can prove UTC/local-day conversion.
    boundary_matches = [
        event for event in history
        if all(event.get(key) == value for key, value in boundary.items())
    ]
    assert boundary_matches == [boundary]
    assert all(
        event == boundary
        or datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00")).date()
        == datetime.fromisoformat(event["reviewedAt"].replace("Z", "+00:00")).astimezone(zone).date()
        for event in history
    )


def test_p9_fixture_schema_keeps_exact_nested_review_calendar_keys() -> None:
    fixture = _json(ROOT / "ops/fixtures/ui_worlds/marketing_demo.json")
    surface = fixture["scenarioContext"]["surfaceContracts"]
    review_calendar = surface["reviewCalendar"]

    assert set(surface) == {"reviewCalendar"}
    assert set(review_calendar) == {"required", "counterexamples"}
    for group in ("required", "counterexamples"):
        assert review_calendar[group]
        assert all(
            set(row) == {"fixtureID", "stepLabel", "index", "assetIDs"}
            for row in review_calendar[group]
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
        boundary = plan["review_calendar_boundary_event"]
        assert all(
            event == boundary or lo <= event_hours[index] <= hi
            for index, event in enumerate(history)
        ), (
            f"{path}: reviewHistory UTC hours escaped history_plan window "
            f"[{lo},{hi}]: {sorted(set(event_hours))}"
        )
        assert [event for event in history if all(
            event.get(key) == value for key, value in boundary.items()
        )] == [boundary]
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
    assert "datasetSHA256" in ui_test
    assert "sourceCommit" in ui_test
    assert "device" in ui_test
    assert "type" in ui_test
    assert "installedFixture" in ui_test


def test_p9_swift_decoders_reject_unknown_keys_at_nested_boundaries() -> None:
    app_seed = _text(IOS / "BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift")
    ui_test = _text(IOS / "BooksAndVocabUITests/FixtureDatasetUITests.swift")

    for declaration in (
        "struct UIWorldSurfaceContractsSeed:",
        "struct UIWorldReviewCalendarEvidenceGroupsSeed:",
        "struct UIWorldReviewCalendarEvidenceSeed:",
        "struct UIWorldInstalledFixtureProof:",
    ):
        assert declaration in app_seed
        section = app_seed.split(declaration, 1)[1].split("\nstruct ", 1)[0]
        assert "init(from decoder: Decoder) throws" in section, declaration
        assert "rejectUnknownKeys" in section, declaration

    assert "AnyCodingKey" in app_seed
    assert "unknownKeys" in app_seed

    for declaration in (
        "struct ReviewClock: Decodable {",
        "struct EvidenceAsset: Decodable {",
        "struct EvidenceGroups: Decodable {",
        "struct GeneratedEvidence: Codable {",
        "struct InstalledFixture: Codable, Equatable {",
        "struct GeneratedEvidenceFile: Codable {",
    ):
        assert declaration in ui_test
        section = ui_test.split(declaration, 1)[1].split("\n        struct ", 1)[0]
        assert "init(from decoder: Decoder) throws" in section, declaration
        assert "rejectUnknownUITestKeys" in section, declaration

    assert "UITestAnyCodingKey" in ui_test
    assert "unknownKeys" in ui_test


def test_malformed_ui_app_args_fail_closed_without_swallowing_decode_errors() -> None:
    launch = _text(IOS / "BooksAndVocabUITests/Helpers/UITestAppLaunch.swift")
    tests = _text(IOS / "BooksAndVocabUITests/BooksAndVocabUITests.swift")

    assert "try? JSONDecoder().decode([String].self" not in launch
    assert "decodeInheritedLaunchArguments" in launch
    assert "preconditionFailure" in launch
    assert "testMalformedInheritedLaunchArgumentsFailClosed" in tests


def test_p9_evidence_cli_and_environment_surface_is_documented() -> None:
    tech_index = _text(ROOT / "docs/reference/tech_index.md")

    assert "`p9_review_calendar_evidence.py`" in tech_index
    for surface in (
        "validate",
        "--workspace-root",
        "--outer-verdict",
        "KG_UI_TEST_APP_ARGS_JSON",
        "KG_P9_INSTALLED_FIXTURE_PROOF_RELATIVE_PATH",
        "KG_UI_TEST_SOURCE_COMMIT",
        "KG_UI_TEST_DATASET_SHA256",
        "KG_UI_TEST_DEVICE_UDID",
    ):
        assert surface in tech_index


def test_installed_fixture_proof_is_app_materialized_and_runner_read_only() -> None:
    ui_test = _text(IOS / "BooksAndVocabUITests/FixtureDatasetUITests.swift")
    store = _text(IOS / "BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift")

    assert "KG_P9_INSTALLED_FIXTURE_PROOF_RELATIVE_PATH" in ui_test
    assert "retrievedPath" in ui_test
    assert "data.write(to: installedURL" not in ui_test
    assert "canonical" in store
    assert "materialized" in store
    assert "KG_P9_INSTALLED_FIXTURE_PROOF_RELATIVE_PATH" in store


def test_review_calendar_render_path_only_reads_cached_proof() -> None:
    presenter = _text(IOS / "BooksAndVocab/Views/Vocabulary/Scenes/ReviewCalendarPresenter.swift")
    store = _text(IOS / "BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift")

    assert "preparedEvidenceFixtureProofValue" in presenter
    assert "materializeEvidenceFixture" not in presenter
    assert "JSONEncoder" not in presenter
    assert "Data(contentsOf:" not in presenter
    assert "JSONEncoder" in store
    prepared_accessor = store.split("static func preparedEvidenceFixtureProofValue()", 1)[1].split("\n    }", 1)[0]
    assert "JSONEncoder" not in prepared_accessor
    assert "Data(contentsOf:" not in prepared_accessor
    assert "SHA256" not in prepared_accessor


def test_empty_day_exposes_selected_state_and_exact_zero_count() -> None:
    presenter = _text(IOS / "BooksAndVocab/Views/Vocabulary/Scenes/ReviewCalendarPresenter.swift")
    page = _text(IOS / "BooksAndVocabUITests/Pages/OverviewPage.swift")
    ui_test = _text(IOS / "BooksAndVocabUITests/FixtureDatasetUITests.swift")

    assert "emptyDaySummary" in presenter
    assert "emptyDaySummary" in page
    assert re.search(r"emptyDaySummary.*?value.*?Int\(value\)", ui_test, re.DOTALL)
    assert "emptyDaySummary.assertExists" in ui_test


def test_ios_test_publishes_and_validates_p9_sidecar_as_formal_artifact() -> None:
    ios_test = _text(ROOT / "ops/ios_test.sh")

    assert "p9_review_calendar_evidence.py" in ios_test
    assert "outer-verdict" in ios_test
    assert "p9ReviewCalendarEvidence" in ios_test
    assert "datasetSHA256" in ios_test
    assert "sourceCommit" in ios_test
    assert "retrieve_p9_installed_fixture_proof" in ios_test
    assert "ios_device_files.sh" in ios_test
    assert 'pull "Documents/Evidence/$EVIDENCE_DATASET_ID.json"' in ios_test


def test_ios_test_fails_closed_when_p9_outer_contract_rejects_sidecar() -> None:
    ios_test = _text(ROOT / "ops/ios_test.sh")

    validation_block = ios_test.split(
        'if [[ -n "$p9_manifest" ]] && ! validate_p9_review_calendar_sidecar',
        1,
    )[1].split("\n  fi", 1)[0]
    assert "return 1" in validation_block


def test_p9_outer_path_contract_resolves_macos_private_var_alias(tmp_path: Path) -> None:
    """The outer verdict may retain /var while the validator sees /private/var."""
    workspace = tmp_path / "evidence"
    workspace.mkdir()
    screenshot = workspace / "01-calendar.png"
    screenshot.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6360f8cfc0000000040001ff8944890000000049454e44ae426082"
        )
    )
    fixture = workspace / "installed-fixture.json"
    fixture.write_text(
        json.dumps({"schema": "kg.fixture.dataset.v2", "datasetID": "marketing_demo"}),
        encoding="utf-8",
    )
    source_commit = "a" * 40
    dataset_sha = "b" * 64
    device = "43FA3E1B-16F8-4144-B17D-53D5E4728FC6"
    selector = "FixtureDatasetUITests/testReviewCalendarRequiredEvidenceUsesStableSelectors"
    record = make_record(
        fixture_id="review-calendar.calendar",
        step_label="calendar",
        manifest_asset_id="review-calendar.calendar",
        manifest_path="scenarioContext.surfaceContracts.reviewCalendar.required[0]",
        asset_id="01-calendar",
        artifact_path=screenshot,
        selector=selector,
        source="ios/BooksAndVocabUITests/FixtureDatasetUITests.swift",
        dataset_id="marketing_demo",
        device=device,
        group="required",
        installed_fixture_path=fixture,
        workspace_root=workspace,
        source_commit=source_commit,
        dataset_sha256=dataset_sha,
    )
    manifest = {
        "schema": EVIDENCE_SCHEMA,
        "sourceCommit": source_commit,
        "datasetID": "marketing_demo",
        "datasetSHA256": dataset_sha,
        "device": device,
        "selector": selector,
        "records": [record],
    }
    manifest_path = workspace / "p9_review_calendar_review_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    alias_root = tmp_path / "private-var-alias"
    alias_root.symlink_to(workspace, target_is_directory=True)
    alias_path = alias_root / manifest_path.name
    outer_verdict = {
        "artifacts": {
            "p9ReviewCalendarEvidence": {
                "schema": EVIDENCE_SCHEMA,
                "path": str(alias_path),
                "sourceCommit": source_commit,
                "datasetID": "marketing_demo",
                "datasetSHA256": dataset_sha,
                "device": device,
                "selector": selector,
                "recordCount": 1,
            }
        }
    }

    validated = validate_manifest_file(
        manifest_path,
        workspace_root=workspace,
        outer_verdict=outer_verdict,
    )

    assert validated["count"] == 1


def test_overview_page_requires_exactly_one_selector_match() -> None:
    source = _text(IOS / "BooksAndVocabUITests/Pages/OverviewPage.swift")

    assert ".firstMatch" not in source
    assert "query.count" in source
    assert "element(boundBy: 0)" in source
