from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ui_world_manifest", ROOT / "ops" / "ui_world_manifest.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

UIWorldManifestError = MODULE.UIWorldManifestError
validate_fixture_dataset_file = MODULE.validate_fixture_dataset_file
build_p1_dictionary_surface_contract = MODULE.build_p1_dictionary_surface_contract


def _marketing_demo() -> dict:
    return json.loads((ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").read_text(encoding="utf-8"))


def test_marketing_demo_declares_canonical_explore_shared_decks_contract():
    data = _marketing_demo()
    catalog = data["sharedDecks"]
    assert set(catalog["fixtures"]) == {
        "loading", "loaded", "empty", "retry",
        "empty-counterexample", "retry-counterexample",
    }
    assert set(catalog["decks"]) == {
        "deck_official_gre_high_freq", "deck_counterexample_retry",
    }
    assert catalog["fixtures"]["loaded"]["deckIDs"] == ["deck_official_gre_high_freq"]
    assert catalog["fixtures"]["retry-counterexample"]["deckIDs"] == ["deck_counterexample_retry"]
    assert catalog["fixtures"]["loaded"]["assetIDs"] == ["images.explore_required"]
    assert catalog["fixtures"]["retry-counterexample"]["assetIDs"] == [
        "images.explore_counterexample_retry"
    ]
    title = catalog["decks"]["deck_official_gre_high_freq"]["title"]
    assert len(title) >= 80
    assert "🧭" in title
    assert any("\u0590" <= char <= "\u08ff" for char in title)


def test_validate_rejects_ui_world_without_top_level_shared_decks(tmp_path: Path):
    data = _marketing_demo()
    data.pop("sharedDecks")
    path = tmp_path / "missing_shared_decks.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(UIWorldManifestError, match=r"top-level keys .*sharedDecks"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_shared_deck_asset_from_non_image_bucket(tmp_path: Path):
    data = _marketing_demo()
    data["sharedDecks"]["fixtures"]["loaded"]["assetIDs"] = ["books.catalog_reader_epub"]
    path = tmp_path / "shared_decks_wrong_asset_type.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(UIWorldManifestError, match=r"sharedDecks.*images"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_stale_explore_surface_contract_projection(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"]["surfaceContracts"]["explore"]["required"][0]["fixtureID"] = "explore.rich-catalog"
    path = tmp_path / "stale_explore_surface_contract.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(UIWorldManifestError, match=r"surfaceContracts\.explore.*projection.*sharedDecks"):
        validate_fixture_dataset_file(path)


def _vocabulary_override(word: str, *, card_role: str = "learning", review_eligible: bool = True) -> dict:
    return {
        "word": word,
        "cardRole": card_role,
        "reviewEligible": review_eligible,
        "reviewIntervalHours": 24,
        "nextReviewAt": "2099-01-01T00:00:00Z",
        "lastReviewedAt": None,
        "reviewCount": 0,
        "reviewStreak": 0,
        "lastReviewFeedbackRaw": -1,
    }
def _asset_path(data: dict, ref: str) -> Path:
    bucket, asset_id = ref.split(".", 1)
    raw = Path(data["assets"][bucket][asset_id]["sourcePath"])
    return raw if raw.is_absolute() else ROOT / raw


def test_reader_real_book_is_a_distinguishable_two_chapter_epub() -> None:
    data = _marketing_demo()
    asset = data["assets"]["books"]["reader_real_book_epub"]
    path = _asset_path(data, "books.reader_real_book_epub")

    assert path.is_relative_to(ROOT), "P3 asset must resolve inside this worktree"
    assert asset["sourcePath"] == "ops/fixtures/assets/reader-real-book.epub"
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert {"OEBPS/chapter1.xhtml", "OEBPS/chapter2.xhtml"} <= names
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        assert 'href="chapter1.xhtml"' in nav
        assert 'href="chapter2.xhtml"' in nav
        chapter_a = archive.read("OEBPS/chapter1.xhtml").decode("utf-8")
        chapter_b = archive.read("OEBPS/chapter2.xhtml").decode("utf-8")
        assert "Introduction" in chapter_a
        assert "Chapter Two" in chapter_b
        assert "Introduction" not in chapter_b


def test_reader_invalid_destination_asset_is_declared_and_really_broken() -> None:
    data = _marketing_demo()
    asset = data["assets"]["books"]["reader_invalid_destination_epub"]
    path = _asset_path(data, "books.reader_invalid_destination_epub")

    assert path.is_relative_to(ROOT), "P3 counterexample asset must resolve inside this worktree"
    assert asset["sourcePath"] == "ops/fixtures/assets/reader-invalid-destination.epub"
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        destinations = re.findall(r'href="([^"]+)"', nav)
        assert destinations
        missing_destinations = [
            destination
            for destination in destinations
            if f"OEBPS/{destination}" not in names
        ]
        assert missing_destinations == ["chapter-missing.xhtml"]
        assert destinations.count("chapter-missing.xhtml") == 1


def test_fixture_store_preflights_destination_realpath_before_mutation() -> None:
    source = _swift_source(
        "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift"
    )
    install_source = source.split(
        "static func requireInstalledAssetURL(ref: String)", 1
    )[1].split("/// Returns proof", 1)[0]

    assert "validateDestinationContainment" in install_source
    preflight = install_source.index("validateDestinationContainment")
    create = install_source.index("createDirectory")
    remove = install_source.index("removeItem")
    copy = install_source.index("copyItem")
    assert preflight < create < remove < copy
    assert "resolvingSymlinksInPath" in source


def test_fixture_store_has_destination_symlink_escape_regression() -> None:
    source = _swift_source(
        "ios/BooksAndVocabTests/FixtureDatasetStoreTests+DomainC.swift"
    )
    assert "destinationSymlinkEscape" in source
    assert "createSymbolicLink" in source
    assert "requireInstalledAssetURL" in source


def test_reader_evidence_selectors_require_exact_cardinality() -> None:
    page = _swift_source("ios/BooksAndVocabUITests/Pages/ReaderPage.swift")
    writer = _swift_source(
        "ios/BooksAndVocabUITests/Helpers/ReaderTOCEvidence.swift"
    )

    for source in (page, writer):
        assert ".firstMatch" not in source
        assert "boundBy: 0" not in source
    assert "element(matching:" in page
    assert "element(matching:" in writer
    assert page.count("count == 1") >= 1
    assert writer.count("count == 1") >= 3


def test_invalid_reader_flow_revalidates_negative_state_after_failure_and_retry() -> None:
    source = _swift_source("ios/BooksAndVocabUITests/ReaderFlowUITests.swift")
    invalid_flow = source.split(
        "func testReaderTOCInvalidRealBookKeepsSheetOpenAndRetryable()", 1
    )[1]

    assert invalid_flow.count("assertFixtureAsset(") >= 3
    assert invalid_flow.count('"OEBPS/chapter1.xhtml"') >= 3
    assert "assertContentAbsent(Self.secondChapterContent)" in invalid_flow
    assert "tocMissingDestinationCount" in invalid_flow
    assert "tocRetryCount" in invalid_flow


def test_reader_evidence_asset_producer_uses_canonical_fixture_proof() -> None:
    source = _swift_source("ios/BooksAndVocab/Views/Reader/ReaderView+Panels.swift")
    evidence_source = _swift_source(
        "ios/BooksAndVocabUITests/Helpers/ReaderTOCEvidence.swift"
    )

    assert "FixtureDatasetStore.readerAssetProof" in source
    assert "Data(contentsOf: url)" not in source
    assert "SHA256.hash(data: data)" not in source
    assert "expectedSHA256" in evidence_source
    assert "expectedByteSize" in evidence_source
    assert "actualSHA256" in evidence_source
    assert "actualByteSize" in evidence_source


def test_reader_evidence_asset_producer_fails_closed_on_missing_proof() -> None:
    source = _swift_source("ios/BooksAndVocab/Views/Reader/ReaderView+Panels.swift")
    producer = source.split("private var readerTOCEvidenceAsset", 1)[1].split(
        "func readerErrorState", 1
    )[0]

    assert "readerAssetProof" in producer
    assert "try?" not in producer
    assert "catch" in producer
    assert "fatalError(" in producer or "preconditionFailure(" in producer


def test_reader_evidence_ui_has_no_silent_skip_or_fallback_contracts() -> None:
    flow = _swift_source("ios/BooksAndVocabUITests/ReaderFlowUITests.swift")
    page = _swift_source("ios/BooksAndVocabUITests/Pages/ReaderPage.swift")
    writer = _swift_source("ios/BooksAndVocabUITests/Helpers/ReaderTOCEvidence.swift")

    for source in (flow, page, writer):
        assert "XCTSkip" not in source
        assert ".firstMatch" not in source
        assert "try?" not in source
    assert "let initialProgress = reader.progressPercent() ?? 0" not in flow
    assert 'progressAfter=\\(reader.progressPercent().map(String.init(describing:)) ?? "<missing>")' not in flow
    assert "as? String ?? \"\"" not in page
    assert "guard let initialHref = reader.currentLocator.value as? String else" in flow
    assert "guard let finalHref = reader.currentLocator.value as? String else" in flow
    assert "guard let invalidInitialHref = reader.currentLocator.value as? String else" in flow


def test_invalid_reader_ui_flow_selects_canonical_missing_destination_row() -> None:
    source = _swift_source("ios/BooksAndVocabUITests/ReaderFlowUITests.swift")
    invalid_flow = source.split(
        "func testReaderTOCInvalidRealBookKeepsSheetOpenAndRetryable()",
        1,
    )[1]

    assert 'currentLocator.value as? String' in invalid_flow
    assert '"OEBPS/chapter1.xhtml"' in invalid_flow
    assert 'contentText("Introduction")' in invalid_flow
    assert 'tocChapter(path: "1", label: "Missing Destination")' in invalid_flow
    assert "evidenceAsset" in invalid_flow


def test_manifest_path_resolver_rejects_parent_traversal() -> None:
    with pytest.raises(UIWorldManifestError, match="escape repo root"):
        MODULE._resolve_path(
            "ops/fixtures/assets/../../../../outside-reader.epub",
            field="sourcePath",
            label="books.reader_real_book_epub",
            require_repo_relative=True,
        )


def test_manifest_path_resolver_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside-reader.epub"
    outside.write_bytes(b"outside")
    link = ROOT / "ops" / "fixtures" / "assets" / ".p3-reader-escape-link"
    try:
        link.symlink_to(outside)
        with pytest.raises(UIWorldManifestError, match="escape repo root"):
            MODULE._resolve_path(
                "ops/fixtures/assets/.p3-reader-escape-link",
                field="sourcePath",
                label="books.reader_real_book_epub",
                require_repo_relative=True,
            )
    finally:
        if link.is_symlink() or link.exists():
            link.unlink()
def _history_plan() -> dict:
    return json.loads((ROOT / "ops" / "demo" / "ui_world_seed" / "history_plan.json").read_text(encoding="utf-8"))


def _plan_review_clock(plan: dict) -> dict:
    anchor = date.fromisoformat(plan["anchor_day"])
    freeze = (
        datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc)
        + timedelta(hours=24 - max(plan["render_utc_offset_hours"]))
        - timedelta(seconds=1)
    )
    time_zone = plan["review_clock_time_zone"]
    assert freeze.astimezone(ZoneInfo(time_zone)).date() == anchor
    return {
        "now": freeze.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozenEpoch": int(freeze.timestamp()),
        "anchorDay": anchor.isoformat(),
        "timeZone": time_zone,
        "source": "history_plan.anchor_day",
    }


def _swift_source(path: str) -> str:
    """Read a canonical Swift fixture declaration, including split siblings."""
    requested = ROOT / path
    sources = [requested]
    if requested.name == "FixtureDatasetStore.swift":
        sources.append(requested.with_name("FixtureDatasetSeeds.swift"))
    return "\n".join(source.read_text(encoding="utf-8") for source in sources)
REVIEW_CARD_EVIDENCE_FIXTURE_IDS = {
    "review.card-full-info",
    "review.card-compact-counterexample",
}
REVIEW_CARD_VISUAL_ASSET_IDS = {
    "compact-back-counterexample",
    "optional-sections-counterexample",
    "small-viewport-counterexample",
    "large-text-counterexample",
}
REVIEW_CARD_UI_FIXTURE_CASES = {
    "review.card-full-info": "notebookReviewCardFullInfo",
    "review.card-compact-counterexample": "notebookReviewCardCompactCounterexample",
}
REVIEW_CARD_CAPTURE_CONTRACTS = {
    "optional-sections-counterexample": {
        "swift_name": "optionalSectionsCounterexample",
        "fixture": "notebookReviewCardCompactCounterexample",
        "identity": "p12CompactCoaxedRecognition",
        "card_id": "review-card-compact-coaxed",
        "word": "coaxed",
        "mode": "recognition",
        "preset": "compact",
        "translation_prefix": "說服、哄勸",
        "minimum_translation_length": 180,
        "effective_profile": "recognition:compact,production:compact",
        "face": "front",
        "presentation": "natural",
        "geometry": "compactFront",
    },
    "compact-back-counterexample": {
        "swift_name": "compactBackCounterexample",
        "fixture": "notebookReviewCardCompactCounterexample",
        "identity": "p12CompactCoaxedRecognition",
        "card_id": "review-card-compact-coaxed",
        "word": "coaxed",
        "mode": "recognition",
        "preset": "compact",
        "translation_prefix": "說服、哄勸",
        "minimum_translation_length": 180,
        "effective_profile": "recognition:compact,production:compact",
        "face": "back",
        "presentation": "natural",
        "geometry": "compactBack",
    },
    "large-text-counterexample": {
        "swift_name": "largeTextCounterexample",
        "fixture": "notebookReviewCardFullInfo",
        "identity": "p13Production",
        "card_id": "review-card-full-coaxed",
        "word": "coaxed",
        "mode": "production",
        "preset": "standard",
        "translation_prefix": "說服；以溫和、耐心",
        "minimum_translation_length": 180,
        "effective_profile": "recognition:standard,production:standard",
        "face": "front",
        "presentation": "natural",
        "geometry": "fullFront",
    },
    "small-viewport-counterexample": {
        "swift_name": "smallViewportCounterexample",
        "fixture": "notebookReviewCardFullInfo",
        "identity": "p13Production",
        "card_id": "review-card-full-coaxed",
        "word": "coaxed",
        "mode": "production",
        "preset": "standard",
        "translation_prefix": "說服；以溫和、耐心",
        "minimum_translation_length": 180,
        "effective_profile": "recognition:standard,production:standard",
        "face": "back",
        "presentation": "scroll",
        "geometry": "fullBack",
    },
}


def _swift_fixture_ids(path: str, enum_name: str) -> set[str]:
    source = _swift_source(path)
    match = re.search(rf"enum {enum_name}: String, CaseIterable \{{(?P<body>.*?)\n\}}", source, flags=re.S)
    assert match, f"missing Swift enum {enum_name}"
    fixture_ids = set()
    for line in match.group("body").splitlines():
        case_match = re.match(r'\s*case\s+(\w+)(?:\s*=\s*"([^"]+)")?', line)
        if case_match:
            fixture_ids.add(case_match.group(2) or case_match.group(1))
    assert fixture_ids, f"missing cases for Swift enum {enum_name}"
    return fixture_ids


def _swift_string_set(path: str, constant_name: str) -> set[str]:
    source = _swift_source(path)
    match = re.search(rf"static let {constant_name}: Set<String> = \[(?P<body>.*?)\n\s*\]", source, flags=re.S)
    assert match, f"missing Swift Set constant {constant_name}"
    values = set(re.findall(r'"([^"]+)"', match.group("body")))
    assert values, f"missing values for Swift Set constant {constant_name}"
    return values


def test_validate_accepts_repo_ui_world():
    dataset_id = validate_fixture_dataset_file(ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json")

    assert dataset_id == "marketing_demo"


def test_validator_rejects_absolute_or_escaping_asset_source_paths(tmp_path: Path):
    data = _marketing_demo()
    cases = [
        (
            str((ROOT.parent / "outside-reader.epub").resolve()),
            "absolute-source.json",
            "sourcePath.*repo-relative",
        ),
        (
            "ops/fixtures/assets/reader-does-not-exist.epub",
            "broken-source.json",
            "sourcePath 不存在",
        ),
    ]
    for source_path, file_name, message in cases:
        case_data = json.loads(json.dumps(data))
        case_data["assets"]["books"]["reader_real_book_epub"]["sourcePath"] = source_path
        path = tmp_path / file_name
        path.write_text(json.dumps(case_data), encoding="utf-8")

        with pytest.raises(UIWorldManifestError, match=message):
            validate_fixture_dataset_file(path)


def test_reader_invalid_destination_ui_flow_is_real_and_retryable():
    source = (ROOT / "ios/BooksAndVocabUITests/ReaderFlowUITests.swift").read_text(encoding="utf-8")
    launch = (ROOT / "ios/BooksAndVocabUITests/Helpers/UITestAppLaunch.swift").read_text(encoding="utf-8")
    seed = (ROOT / "ios/BooksAndVocab/Support/UITestFixtureSeed+Reader.swift").read_text(encoding="utf-8")

    assert "readerInvalidDestinationLibrary" in source
    assert "reader:invalidDestinationLibrary" in launch
    assert '"invalidDestinationLibrary"' in seed
    assert "reader.toc.missingDestination" in source
    assert "reader.toc.retry" in source
    match = re.search(
        r"func testReaderTOCInvalidRealBookKeepsSheetOpenAndRetryable\(\) throws \{(?P<body>.*?)\n    \}",
        source,
        flags=re.S,
    )
    assert match, "missing real invalid-book UI flow"
    body = match.group("body")
    assert "waitUntilTableOfContentsSheetExists" in body
    assert "tocMissingDestination" in body
    assert "tocRetry" in body
    page = (ROOT / "ios/BooksAndVocabUITests/Pages/ReaderPage.swift").read_text(encoding="utf-8")
    assert '"reader.toc.missingDestination"' in page
    assert '"reader.toc.retry"' in page
    assert "tocDone.isEnabled" in body
    assert "tableOfContentsSheet.waitUntilGone" not in body
    assert "FakeReaderNavigator" not in body
    assert "does-not-exist" not in body


def test_repo_fixture_asset_sources_are_relative_and_reproducible():
    data = _marketing_demo()

    for bucket, assets in data["assets"].items():
        for asset_id, asset in assets.items():
            source_path = Path(asset["sourcePath"])
            assert not source_path.is_absolute(), (
                f"assets.{bucket}.{asset_id}.sourcePath must be repo-relative"
            )
            assert not any(part in {".", ".."} for part in source_path.parts), (
                f"assets.{bucket}.{asset_id}.sourcePath must not contain traversal"
            )

    assert validate_fixture_dataset_file(
        ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"
    ) == "marketing_demo"


def test_git_fixture_asset_identity_is_path_hash_and_size_only():
    data = _marketing_demo()

    for bucket, assets in data["assets"].items():
        for asset_id, asset in assets.items():
            assert set(asset) == {
                "sourcePath", "sha256", "installAs", "byteSize", "contentType"
            }, f"assets.{bucket}.{asset_id} must not persist runtime filesystem identity"
            assert "inode" not in json.dumps(asset)


@pytest.mark.parametrize("field", ["sourcePath", "sha256", "byteSize", "contentType"])
def test_validate_rejects_missing_asset_provenance_field(tmp_path: Path, field: str):
    data = _marketing_demo()
    del data["assets"]["books"]["catalog_reader_epub"][field]
    path = tmp_path / f"missing_asset_{field}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.books\.catalog_reader_epub keys 不符合 UI World v2"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize(
    "source_path",
    [
        str(ROOT / "ops" / "fixtures" / "assets" / "catalog-reader.epub"),
        "../AGENTS.md",
    ],
)
def test_validate_rejects_absolute_or_escaping_asset_source_path(tmp_path: Path, source_path: str):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["sourcePath"] = source_path
    path = tmp_path / "unsafe_source_path.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"sourcePath.*repo-relative"):
        validate_fixture_dataset_file(path)


def test_marketing_demo_review_clock_is_explicit_and_history_aligned():
    data = _marketing_demo()
    clock = data["scenarioContext"]["reviewClock"]
    expected = _plan_review_clock(_history_plan())

    assert clock == expected
    assert data["scenarioContext"]["surfaceContracts"]["reviewCalendar"]
    assert validate_fixture_dataset_file(
        ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json",
        require_review_clock=True,
        require_review_history_alignment=True,
    ) == "marketing_demo"


def test_review_clock_validator_rejects_history_after_anchor(tmp_path: Path):
    data = _marketing_demo()
    data["vocabulary"]["reviewCalendarDense"]["reviewHistory"] = [
        dict(item, reviewedAt="2026-07-10T12:00:00Z")
        for item in data["vocabulary"]["reviewCalendarDense"]["reviewHistory"]
    ]
    path = tmp_path / "clock_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="latest exceeds|history day exceeds"):
        validate_fixture_dataset_file(
            path,
            require_review_clock=True,
            require_review_history_alignment=True,
        )


def test_review_clock_validator_rejects_epoch_anchor_mismatch(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"]["reviewClock"] = {
        "now": "2026-07-09T14:59:59Z",
        "frozenEpoch": 0,
        "anchorDay": "2026-07-09",
        "timeZone": "Pacific/Honolulu",
        "source": "history_plan.anchor_day",
    }
    path = tmp_path / "clock_epoch_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="now/frozenEpoch|anchorDay"):
        validate_fixture_dataset_file(
            path,
            require_review_clock=True,
            require_review_history_alignment=True,
        )


def test_review_clock_validator_rejects_missing_scenario_context(tmp_path: Path):
    data = _marketing_demo()
    data.pop("scenarioContext")
    path = tmp_path / "missing_clock_context.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="requires scenarioContext"):
        validate_fixture_dataset_file(path, require_review_clock=True)


def test_review_calendar_evidence_mapping_rejects_duplicate_asset_id(tmp_path: Path):
    data = _marketing_demo()
    rows = data["scenarioContext"]["surfaceContracts"]["reviewCalendar"]["required"]
    rows[1]["assetIDs"] = list(rows[0]["assetIDs"])
    path = tmp_path / "duplicate_review_evidence_asset.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="assetIDs.*unique|one-to-one"):
        validate_fixture_dataset_file(path, require_review_clock=True)


def test_review_calendar_evidence_mapping_rejects_missing_label(tmp_path: Path):
    data = _marketing_demo()
    rows = data["scenarioContext"]["surfaceContracts"]["reviewCalendar"]["required"]
    rows.pop()
    path = tmp_path / "missing_review_evidence_label.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="required.*labels|stepLabel"):
        validate_fixture_dataset_file(path, require_review_clock=True)


@pytest.mark.parametrize(
    ("location", "unknown_key", "unknown_value"),
    (
        ("surfaceContracts", "extra", {}),
        ("reviewCalendar", "extra", {}),
        ("reviewCalendar", "assetInodes", {}),
        ("row", "extra", "retired-wire-field"),
    ),
)
def test_review_calendar_evidence_rejects_unknown_nested_object_keys(
    tmp_path: Path, location: str, unknown_key: str, unknown_value: object
):
    data = _marketing_demo()
    surface = data["scenarioContext"]["surfaceContracts"]
    if location == "surfaceContracts":
        surface[unknown_key] = unknown_value
    elif location == "reviewCalendar":
        surface["reviewCalendar"][unknown_key] = unknown_value
    else:
        surface["reviewCalendar"]["required"][0][unknown_key] = unknown_value
    path = tmp_path / f"unknown_{location}_{unknown_key}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="keys 不符合|evidence row keys"):
        validate_fixture_dataset_file(path, require_review_clock=True)


@pytest.mark.parametrize(
    ("location", "missing_key"),
    (
        ("surfaceContracts", "reviewCalendar"),
        ("reviewCalendar", "required"),
        ("reviewCalendar", "counterexamples"),
        ("row", "assetIDs"),
    ),
)
def test_review_calendar_evidence_rejects_missing_nested_object_keys(
    tmp_path: Path, location: str, missing_key: str
):
    data = _marketing_demo()
    surface = data["scenarioContext"]["surfaceContracts"]
    if location == "surfaceContracts":
        del surface[missing_key]
    elif location == "reviewCalendar":
        del surface["reviewCalendar"][missing_key]
    else:
        del surface["reviewCalendar"]["required"][0][missing_key]
    path = tmp_path / f"missing_{location}_{missing_key}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="keys 不符合|evidence row keys"):
        validate_fixture_dataset_file(path, require_review_clock=True)


def test_review_calendar_evidence_rejects_malformed_nested_keys_when_clock_is_null(
    tmp_path: Path,
):
    data = _marketing_demo()
    data["scenarioContext"]["reviewClock"] = None
    del data["scenarioContext"]["surfaceContracts"]["reviewCalendar"]["required"][0]["assetIDs"]
    path = tmp_path / "null_clock_malformed_review_evidence.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="evidence row keys"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize(
    ("unknown_key", "unknown_value"),
    (("assetInodes", ["checkout-inode"]), ("inode", "checkout-inode")),
)
def test_review_calendar_evidence_mapping_rejects_nested_checkout_identity_key(
    tmp_path: Path, unknown_key: str, unknown_value: object
):
    data = _marketing_demo()
    row = data["scenarioContext"]["surfaceContracts"]["reviewCalendar"]["required"][0]
    row[unknown_key] = unknown_value
    path = tmp_path / f"nested_{unknown_key}_review_evidence.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="evidence row keys"):
        validate_fixture_dataset_file(path, require_review_clock=True)


def test_review_calendar_evidence_mapping_has_no_checkout_identity_fields(tmp_path: Path):
    data = _marketing_demo()
    rows = data["scenarioContext"]["surfaceContracts"]["reviewCalendar"]["required"]
    assert rows
    assert all(set(row) == {"fixtureID", "stepLabel", "index", "assetIDs"} for row in rows)
    path = tmp_path / "portable_review_evidence.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path, require_review_clock=True) == "marketing_demo"

def test_validate_accepts_ui_world_without_optional_scenario_context(tmp_path: Path):
    data = _marketing_demo()
    data.pop("scenarioContext")
    path = tmp_path / "minimal_context.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path) == "marketing_demo"


def test_validate_accepts_all_repo_and_generated_ui_worlds():
    repo_worlds = sorted((ROOT / "ops" / "fixtures" / "ui_worlds").glob("*.json"))
    generated_worlds = [ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"]
    assert repo_worlds

    dataset_ids = [validate_fixture_dataset_file(path) for path in [*repo_worlds, *generated_worlds]]

    assert "marketing_demo" in dataset_ids
    assert "demo-demo-user" in dataset_ids


def test_review_card_evidence_fixtures_materialize_and_keep_asset_id_parity():
    """P12/P13 contract: canonical deck seeds must reach both UI World artifacts.

    The Swift decoder intentionally has no synthetic front/back fields: front and
    back materialization is the non-empty field set consumed by ReviewCardView.
    The screenshot identities are source-level assets, so this contract remains
    executable without starting Xcode or a Simulator.
    """
    assert REVIEW_CARD_EVIDENCE_FIXTURE_IDS <= MODULE.FIXTURE_DOMAIN_IDS["reviewDeck"]

    generated_path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
    repo = _marketing_demo()
    generated = json.loads(generated_path.read_text(encoding="utf-8"))

    assert REVIEW_CARD_EVIDENCE_FIXTURE_IDS <= set(repo["reviewDeck"])
    assert REVIEW_CARD_EVIDENCE_FIXTURE_IDS <= set(generated["reviewDeck"])

    for fixture_id in sorted(REVIEW_CARD_EVIDENCE_FIXTURE_IDS):
        repo_seed = repo["reviewDeck"][fixture_id]
        generated_seed = generated["reviewDeck"][fixture_id]
        assert repo_seed == generated_seed, f"generated drift for reviewDeck.{fixture_id}"
        entries = repo_seed["entries"]
        assert entries, fixture_id
        for entry in entries:
            # Front materialization: identity, difficulty, and mode are present.
            assert entry["word"].strip(), fixture_id
            assert entry["difficultyTier"].strip(), fixture_id
            assert entry["reviewMode"] in {"recognition", "production"}, fixture_id
            # Back materialization: all long-content surfaces are non-empty.
            assert entry["translation"].strip(), fixture_id
            assert entry["context"].strip(), fixture_id
            assert entry["reviewExamples"] and all(
                example.strip() for example in entry["reviewExamples"]
            ), fixture_id

    visual_source = (ROOT / "ios" / "BooksAndVocabUITests" / "ReviewCardLayoutEditorUITests.swift").read_text(
        encoding="utf-8"
    )
    identity_source = (ROOT / "ios" / "BooksAndVocabUITests" / "Pages" / "TodayReviewPage.swift").read_text(
        encoding="utf-8"
    )
    capture_blocks = dict(
        re.findall(
            r"static let (\w+) = ReviewCardVisualEvidenceCapture\(\s*(.*?)\n\s*\)",
            visual_source,
            flags=re.S,
        )
    )
    actual_asset_ids = set(re.findall(r'assetID:\s*"([^"]+-counterexample)"', visual_source))
    assert actual_asset_ids == REVIEW_CARD_VISUAL_ASSET_IDS
    assert set(capture_blocks) == {
        contract["swift_name"] for contract in REVIEW_CARD_CAPTURE_CONTRACTS.values()
    }
    for asset_id, contract in REVIEW_CARD_CAPTURE_CONTRACTS.items():
        block = capture_blocks[contract["swift_name"]]
        assert f'assetID: "{asset_id}"' in block
        assert f'fixture: .{contract["fixture"]}' in block
        assert f'identity: .{contract["identity"]}' in block
        assert f'face: .{contract["face"]}' in block
        assert f'presentation: .{contract["presentation"]}' in block
        assert f'geometry: .{contract["geometry"]}' in block
        identity_block_match = re.search(
            rf"static let {contract['identity']} = CardIdentity\((.*?)\n        \)",
            identity_source,
            flags=re.S,
        )
        assert identity_block_match, contract["identity"]
        identity_block = identity_block_match.group(1)
        assert f'cardID: "{contract["card_id"]}"' in identity_block
        assert f'frontWord: "{contract["word"]}"' in identity_block
        assert f'mode: .{contract["mode"]}' in identity_block
        assert f'preset: .{contract["preset"]}' in identity_block
        assert f'translationPrefix: "{contract["translation_prefix"]}"' in identity_block
        assert f'minimumTranslationLength: {contract["minimum_translation_length"]}' in identity_block
        assert f'effectiveLayoutProfile: "{contract["effective_profile"]}"' in identity_block

        fixture_id = next(
            fixture_id
            for fixture_id, swift_case in REVIEW_CARD_UI_FIXTURE_CASES.items()
            if swift_case == contract["fixture"]
        )
        repo_seed = repo["reviewDeck"][fixture_id]
        generated_seed = generated["reviewDeck"][fixture_id]
        assert repo_seed == generated_seed, f"generated drift for reviewDeck.{fixture_id}"
        entries = [
            entry
            for entry in repo_seed["entries"]
            if entry["kgCardId"] == contract["card_id"]
        ]
        assert len(entries) == 1, f"{asset_id} must have one canonical card entry"
        entry = entries[0]
        assert entry["word"] == contract["word"]
        assert entry["reviewMode"] == contract["mode"]
        assert entry["translation"].startswith(contract["translation_prefix"])
        assert len(entry["translation"]) >= contract["minimum_translation_length"]
        assert entry["difficultyTier"].strip()
        assert entry["context"].strip()
        assert entry["reviewExamples"] and all(
            example.strip() for example in entry["reviewExamples"]
        )

    full_info = repo["reviewDeck"]["review.card-full-info"]["entries"]
    assert {entry["reviewMode"] for entry in full_info} >= {"recognition", "production"}
    assert any(any(len(example) >= 240 for example in entry["reviewExamples"]) for entry in full_info)
    assert any(len(entry["explanation"] or "") >= 240 for entry in full_info)
    assert any(len(entry["collocations"] or []) >= 3 for entry in full_info)
    compact = repo["reviewDeck"]["review.card-compact-counterexample"]["entries"]
    assert any(any(len(example) >= 240 for example in entry["reviewExamples"]) for entry in compact)
    assert any(len(entry["explanation"] or "") >= 240 for entry in compact)


@pytest.mark.parametrize(
    ("domain", "path", "enum_name"),
    [
        ("auth", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift", "UIWorldAuthFixtureID"),
        ("entitlements", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift", "UIWorldEntitlementsFixtureID"),
        ("settings", "ios/BooksAndVocab/Support/Fixtures/Settings/SettingsFixtures.swift", "SettingsFixtureID"),
        ("bookshelf", "ios/BooksAndVocab/Support/Fixtures/Bookshelf/BookshelfFixtures.swift", "BookshelfFixtureID"),
        ("todayReview", "ios/BooksAndVocab/Support/Fixtures/TodayReview/TodayReviewFixtures.swift", "TodayReviewFixtureID"),
        ("notebook", "ios/BooksAndVocab/Support/Fixtures/Notebook/NotebookFixtures.swift", "NotebookFixtureID"),
        ("podcast", "ios/BooksAndVocab/Support/Fixtures/Podcast/PodcastFixtures.swift", "PodcastFixtureID"),
        ("runtimePodcast", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift", "UIWorldRuntimePodcastFixtureID"),
        ("reader", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift", "UIWorldReaderFixtureID"),
        ("vocabulary", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift", "UIWorldVocabularyFixtureID"),
        ("reviewDeck", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift", "UIWorldReviewDeckFixtureID"),
        ("syncPresenter", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift", "UIWorldSyncPresenterFixtureID"),
    ],
)
def test_fixture_domain_ids_are_a_subset_of_swift_fixture_enums(domain: str, path: str, enum_name: str):
    """FROZEN 2026-08-05 — 凍結前這裡是雙向 `==`（Python 鏡像必須等於 Swift enum），
    那是「Swift 加一個 case，Python 常數就得跟著改」的跨語言稅，與 iOS 端那 6 個
    world↔allCases 鎖同類（正本 docs/reference/catalog_scope.md §FROZEN）。

    保留的方向是**健全性**那一邊：`FIXTURE_DOMAIN_IDS ⊆ Swift enum`。validator 拿
    `FIXTURE_DOMAIN_IDS` 當 `known_ids` 做 subset 檢查來擋「world 宣告了 app 不認識的
    fixture id」——若 Python 認得 Swift 不認得的 id，那道檢查就會放行一個渲染不出來的
    world。反方向（Swift 有、Python 沒有）在凍結期只會讓 validator **保守地拒絕**一個
    不該被新增的 id，那正是凍結想要的行為。

    復業第一步＝改回 `==`；完整配方見正本。
    """
    swift_ids = _swift_fixture_ids(path, enum_name)
    # 正控：沒有這行，下面的 subset 對空集合恆真（假綠）。
    assert MODULE.FIXTURE_DOMAIN_IDS[domain], f"{domain} 的 Python 鏡像不該是空的"
    assert swift_ids, f"{enum_name} 解析不到任何 case——解析器壞了，不是 enum 空了"
    assert MODULE.FIXTURE_DOMAIN_IDS[domain] <= swift_ids


@pytest.mark.parametrize(
    ("domain", "swift_constant"),
    [
        ("userDefaults", "userDefaultsKeys"),
        ("ubiquitousKeyValueStore", "ubiquitousKeyValueStoreKeys"),
    ],
)
def test_preference_domain_keys_match_swift_preferences_seed(domain: str, swift_constant: str):
    swift_path = "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetSeeds.swift"

    assert MODULE.PREFERENCE_DOMAIN_KEYS[domain] == _swift_string_set(swift_path, swift_constant)


@pytest.mark.parametrize("domain", sorted(MODULE.FIXTURE_DOMAIN_IDS))
def test_validate_rejects_unknown_fixture_domain_id(tmp_path: Path, domain: str):
    data = _marketing_demo()
    data[domain]["ghostFixture"] = next(iter(data[domain].values()))
    path = tmp_path / f"unknown_{domain}_fixture.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=rf"{domain} fixture ids .*ghostFixture"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_card_null_date_added(tmp_path: Path):
    # Swift TodayReviewCardSeed.dateAdded 是非 optional Date：null 會在 app 內
    # preconditionFailure，validator 必須在這裡就 fail-fast（IMP-0018）。
    data = _marketing_demo()
    data["todayReview"]["front"]["currentCard"]["dateAdded"] = None
    path = tmp_path / "null_today_review_date_added.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview\.front\.currentCard\.dateAdded"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize("domain", ["vocabulary", "reviewDeck"])
def test_validate_rejects_graph_link_to_missing_in_seed_target(tmp_path: Path, domain: str):
    # KnowledgeGraphViewScenarios.swift:199 驗 graph link cardId 必 resolve 同
    # seed entries（Set(entries.kgCardId)）：dangling link 到 app 內才 fatal，
    # validator 必須在這裡 fail-fast。
    data = _marketing_demo()
    mutated = False
    for fixture_id, seed in data[domain].items():
        entries = seed.get("entries", [])
        if not entries:
            continue
        entries[0]["graphLinksByKind"]["shares_usage"] = [{
            "id": "ghost-link", "cardId": "ghost-card-id", "word": "ghostword",
            "kind": "shares_usage", "label": "相關", "confidence": 0.5,
            "reason": "dangling", "hidden": False,
        }]
        mutated = True
        break
    assert mutated, f"baseline {domain} must contain at least one entry to mutate"
    path = tmp_path / f"dangling_{domain}_graph_link.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"graphLinksByKind.*(resolve|missing|in-seed)|in-seed"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_asset_hash_drift(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["sha256"] = "0" * 64
    path = tmp_path / "bad_hash.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="assets.books.catalog_reader_epub.sha256 mismatch"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_zero_byte_asset(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["byteSize"] = 0
    path = tmp_path / "zero_byte.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="byteSize 必須是正整數"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_unknown_asset_property(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["legacyPath"] = "ghost"
    path = tmp_path / "unknown_asset_property.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="keys 不符合 UI World v2"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_duplicate_asset_install_path(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["images"]["notebook_cover_app_icon"]["installAs"] = data["assets"]["books"]["catalog_reader_epub"]["installAs"]
    path = tmp_path / "duplicate_asset_install_path.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.images\.notebook_cover_app_icon\.installAs duplicates assets\.books\.catalog_reader_epub\.installAs"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_asset_content_type_for_wrong_bucket(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["images"]["notebook_cover_app_icon"]["contentType"] = "application/pdf"
    path = tmp_path / "wrong_bucket_content_type.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.images\.notebook_cover_app_icon\.contentType application/pdf is invalid for assets\.images"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_asset_content_type_extension_mismatch(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["contentType"] = "application/pdf"
    path = tmp_path / "asset_content_type_extension_mismatch.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.books\.catalog_reader_epub\.contentType must match \.epub as application/epub\+zip"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_preference_wrapper_key(tmp_path: Path):
    data = _marketing_demo()
    del data["preferences"]["ubiquitousKeyValueStore"]
    path = tmp_path / "missing_preference_wrapper.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences keys .*ubiquitousKeyValueStore"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_unknown_preference_wrapper_key(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["legacyDefaults"] = {}
    path = tmp_path / "unknown_preference_wrapper.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences keys .*legacyDefaults"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_invalid_preference_value_type(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["userDefaults"]["auto_sync_enabled"] = None
    path = tmp_path / "invalid_preference_value.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="preferences.userDefaults.auto_sync_enabled"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_unknown_user_defaults_preference_key(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["userDefaults"]["translation_source_lagn"] = "en"
    path = tmp_path / "unknown_user_defaults_preference_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences.userDefaults contains unknown app preference keys .*translation_source_lagn"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_local_only_preference_in_icloud_kvs(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["ubiquitousKeyValueStore"]["auto_sync_enabled"] = True
    path = tmp_path / "local_only_preference_in_icloud_kvs.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences.ubiquitousKeyValueStore contains unknown app preference keys .*auto_sync_enabled"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_runtime_download_local_path(tmp_path: Path):
    data = _marketing_demo()
    del data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["localAudioPath"]
    path = tmp_path / "missing_download_local_path.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"download keys .*localAudioPath"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_unknown_runtime_download_key(tmp_path: Path):
    data = _marketing_demo()
    data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["downloaded"] = True
    path = tmp_path / "unknown_download_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"download keys .*downloaded"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_runtime_download_local_path_drift(tmp_path: Path):
    data = _marketing_demo()
    data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["localAudioPath"] = "podcast-downloads/wrong.m4a"
    path = tmp_path / "download_local_path_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="localAudioPath must match asset installAs"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_runtime_download_subtitle_path_without_subtitle_ref(tmp_path: Path):
    data = _marketing_demo()
    download = data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]
    download["subtitleAssetRef"] = None
    path = tmp_path / "download_subtitle_path_without_ref.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="localSubtitlePath must be null"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_runtime_download_asset_ref(tmp_path: Path):
    data = _marketing_demo()
    data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["audioAssetRef"] = "audio.missing"
    path = tmp_path / "missing_runtime_audio.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="download.audioAssetRef references missing audio.missing"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_auth_state_drift(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["auth"]["email"] = "drift@example.com"
    path = tmp_path / "settings_auth_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="settings.subscription_free.auth.email must match auth.settingsSignedIn.email"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_seed_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["settings"]["logged_out"]["bookSync"]
    path = tmp_path / "settings_missing_nullable_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.logged_out keys .*bookSync"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_seed_unknown_nested_key(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["preferences"]["legacyTheme"] = "sepia"
    path = tmp_path / "settings_unknown_nested_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.preferences keys .*legacyTheme"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_review_invalid_mode(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["reviewSettings"]["mode"] = "turbo"
    path = tmp_path / "settings_bad_review_mode.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.reviewSettings.mode is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_review_interval_drift(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["reviewSettings"]["customMinimumIntervalHours"] = 48
    data["settings"]["subscription_free"]["reviewSettings"]["customMaximumIntervalHours"] = 24
    path = tmp_path / "settings_bad_review_interval.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"customMaximumIntervalHours must be >= customMinimumIntervalHours"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_local_server_without_observation(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["debug_backend_local"]["kg"]["observation"] = None
    path = tmp_path / "settings_local_server_without_observation.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.debug_backend_local.kg.observation is required"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_subscription_invalid_badge_tone(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["subscription"]["badgeTone"] = "danger"
    path = tmp_path / "settings_bad_badge_tone.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.subscription.badgeTone is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_book_sync_invalid_tone(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["bookSync"]["tone"] = "idle"
    path = tmp_path / "settings_bad_book_sync_tone.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.bookSync.tone is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_logged_in_auth_without_user_id(tmp_path: Path):
    data = _marketing_demo()
    data["auth"]["signedIn"]["userId"] = None
    path = tmp_path / "missing_logged_in_user_id.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="auth.signedIn.userId"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_auth_seed_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["auth"]["signedIn"]["providerUserId"]
    path = tmp_path / "missing_nullable_auth_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"auth.signedIn keys .*providerUserId"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_auth_seed_unknown_key(tmp_path: Path):
    data = _marketing_demo()
    data["auth"]["signedIn"]["legacyUserId"] = "user-legacy"
    path = tmp_path / "unknown_auth_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"auth.signedIn keys .*legacyUserId"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_entitlements_seed_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["entitlements"]["pro"]["pro"]["price_display"]
    path = tmp_path / "missing_nullable_entitlement_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.pro.pro keys .*price_display"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_entitlements_seed_unknown_key(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["pro"]["pro"]["is_admin_granted"] = False
    path = tmp_path / "unknown_entitlement_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.pro.pro keys .*is_admin_granted"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_entitlements_active_status_drift(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["free"]["pro"]["is_active"] = True
    path = tmp_path / "entitlement_active_status_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.free.pro.is_active must match entitlement-bearing status"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_admin_entitlement_with_app_store_product(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["adminGranted"]["pro"]["product_id"] = "com.wordnexus.pro.monthly"
    path = tmp_path / "admin_entitlement_with_app_store_product.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.adminGranted.pro admin source must not carry App Store product"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_entitlements_invalid_sync_timestamp(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["pro"]["pro"]["last_synced_at"] = "yesterday"
    path = tmp_path / "entitlement_bad_timestamp.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.pro.pro.last_synced_at must be ISO8601"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_book_install_drift(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["installAs"] = "Books/wrong.epub"
    path = tmp_path / "book_install_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="installAs must be Books/catalog-reader.epub"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_seed_missing_reference_date(tmp_path: Path):
    data = _marketing_demo()
    del data["bookshelf"]["with_books_library"]["referenceDate"]
    path = tmp_path / "bookshelf_missing_reference_date.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"bookshelf.with_books_library keys .*referenceDate"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_book_unknown_row_key(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["legacyProgress"] = 0.1
    path = tmp_path / "bookshelf_unknown_book_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"bookshelf.with_books_library.books\[0\] keys .*legacyProgress"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_progression_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["progression"] = 1.1
    path = tmp_path / "bookshelf_bad_progression.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"progression must be between 0 and 1"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_invalid_date(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["dateAdded"] = "not-a-date"
    path = tmp_path / "bookshelf_bad_date.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"dateAdded must be ISO8601"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_last_read_before_added(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["dateAdded"] = "2026-01-06T00:00:00Z"
    data["bookshelf"]["with_books_library"]["books"][0]["dateLastRead"] = "2026-01-05T00:00:00Z"
    path = tmp_path / "bookshelf_last_read_before_added.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"dateLastRead must not be earlier than dateAdded"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_preferred_notebook_ref(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["reader_notebook_bound"]["books"][0]["preferredNotebookId"] = "missing-nb"
    path = tmp_path / "missing_preferred_notebook.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="preferredNotebookId references missing notebook missing-nb"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_notebook_cover_asset_ref(tmp_path: Path):
    data = _marketing_demo()
    data["notebook"]["coverGallery"]["notebooks"][0]["coverImageAssetRef"] = "images.missing"
    path = tmp_path / "missing_notebook_cover.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="coverImageAssetRef references missing images.missing"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_notebook_sync_status_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["notebook"]["populated"]["notebooks"][0]["syncStatus"] = 9
    path = tmp_path / "notebook_bad_sync_status.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"notebook.populated.notebooks\[0\].syncStatus"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_notebook_card_count_drift(tmp_path: Path):
    data = _marketing_demo()
    data["notebook"]["cardGallery"]["notebooks"][0]["cardState"]["cardCount"] = 1
    path = tmp_path / "notebook_card_count_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="cardCount must equal dueCount"):
        validate_fixture_dataset_file(path)


def test_validate_accepts_notebook_entry_review_scheduling_fields(tmp_path: Path):
    # Notebook list 徽章/進度條資料面：entry 可帶 optional review scheduling
    # 欄位（與 Swift NotebookEntrySeed decodeIfPresent 對齊）。
    data = _marketing_demo()
    data["notebook"]["populated"]["notebooks"][0]["entries"][0].update({
        "reviewIntervalHours": 48.0,
        "nextReviewAt": "2026-07-09T00:00:00Z",
        "lastReviewedAt": "2026-07-07T12:00:00Z",
        "reviewCount": 4,
    })
    data["notebook"]["populated"]["notebooks"][0]["entries"][1].update({
        "reviewIntervalHours": None,
        "nextReviewAt": None,
        "lastReviewedAt": None,
        "reviewCount": None,
    })
    path = tmp_path / "notebook_review_fields.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path) == "marketing_demo"


def test_validate_accepts_notebook_entry_without_review_fields(tmp_path: Path):
    # optional 契約：baseline-kept fixture（readerPicker* / cardGallery 等）
    # 不帶 review 欄位仍必須通過。
    data = _marketing_demo()
    for seed in data["notebook"].values():
        for notebook in seed["notebooks"]:
            for entry in notebook["entries"]:
                for key in ("reviewIntervalHours", "nextReviewAt", "lastReviewedAt", "reviewCount"):
                    entry.pop(key, None)
    path = tmp_path / "notebook_no_review_fields.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path) == "marketing_demo"


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("reviewCount", -1, r"reviewCount must be non-negative"),
        ("reviewIntervalHours", -1.0, r"reviewIntervalHours must be null or a non-negative number"),
        ("nextReviewAt", "not-a-date", r"nextReviewAt must be ISO8601"),
        ("lastReviewedAt", "not-a-date", r"lastReviewedAt must be ISO8601"),
    ],
)
def test_validate_rejects_notebook_entry_bad_review_fields(tmp_path: Path, field: str, bad_value, message: str):
    data = _marketing_demo()
    data["notebook"]["populated"]["notebooks"][0]["entries"][0][field] = bad_value
    path = tmp_path / f"notebook_bad_review_{field}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=rf"notebook.populated.notebooks\[0\].entries\[0\].{message}"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_notebook_entry_unknown_key(tmp_path: Path):
    data = _marketing_demo()
    data["notebook"]["populated"]["notebooks"][0]["entries"][0]["reviewStreak"] = 3
    path = tmp_path / "notebook_entry_unknown_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"notebook.populated.notebooks\[0\].entries\[0\] keys 不符合"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_vocabulary_duplicate_entry_words(tmp_path: Path):
    data = _marketing_demo()
    entry = dict(data["vocabulary"]["vocabLinkedCards"]["entries"][0])
    data["vocabulary"]["vocabLinkedCards"]["entries"].append(entry)
    path = tmp_path / "vocabulary_duplicate_entries.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="vocabulary.vocabLinkedCards.entries.word must not contain duplicate values"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_vocabulary_review_history_missing_entry_ref(tmp_path: Path):
    data = _marketing_demo()
    data["vocabulary"]["vocabLinkedCards"]["reviewHistory"] = [
        {"word": "missing-word", "feedback": 1, "reviewedAt": "2026-01-01T00:00:00Z"}
    ]
    path = tmp_path / "vocabulary_review_history_missing_entry.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"reviewHistory\[0\].missing-word must reference an entry"):
        validate_fixture_dataset_file(path)


def test_validate_resolves_multi_level_vocabulary_inheritance(tmp_path: Path):
    data = _marketing_demo()
    base_words = [entry["word"] for entry in data["vocabulary"]["vocabListLong"]["entries"]]
    data["vocabulary"]["vocabListEmpty"].update({
        "baseFixture": "vocabListLong",
        "entryOverrides": [_vocabulary_override(base_words[0])],
    })
    data["vocabulary"]["vocabListSingle"].update({
        "baseFixture": "vocabListEmpty",
        "entries": [],
        "entryOverrides": [_vocabulary_override(base_words[1])],
    })
    path = tmp_path / "vocabulary_multi_level_inheritance.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path) == "marketing_demo"


def test_validate_rejects_vocabulary_inheritance_cycle(tmp_path: Path):
    data = _marketing_demo()
    data["vocabulary"]["vocabListEmpty"]["baseFixture"] = "vocabListSingle"
    data["vocabulary"]["vocabListSingle"].update({
        "baseFixture": "vocabListEmpty",
        "entries": [],
    })
    path = tmp_path / "vocabulary_inheritance_cycle.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"vocabulary inheritance cycle: .*vocabListEmpty.*vocabListSingle"):
        validate_fixture_dataset_file(path)


def test_validate_reports_vocabulary_cycle_before_override_semantics(tmp_path: Path):
    data = _marketing_demo()
    malformed_override = _vocabulary_override("missing", card_role="malformed")
    malformed_override.update({
        "reviewIntervalHours": -1,
        "nextReviewAt": "not-a-date",
        "lastReviewedAt": "not-a-date",
        "reviewCount": -1,
        "reviewStreak": -1,
    })
    data["vocabulary"]["vocabListEmpty"].update({
        "baseFixture": "vocabListSingle",
        "entryOverrides": [
            malformed_override,
            _vocabulary_override("also-missing", card_role="dictionary", review_eligible=True),
        ],
    })
    data["vocabulary"]["vocabListSingle"].update({
        "baseFixture": "vocabListEmpty",
        "entries": [],
    })
    path = tmp_path / "vocabulary_cycle_with_malformed_override.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"vocabulary inheritance cycle"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_inherited_override_missing_word(tmp_path: Path):
    data = _marketing_demo()
    data["vocabulary"]["vocabListEmpty"].update({
        "baseFixture": "vocabListLong",
        "entryOverrides": [_vocabulary_override("missing-from-resolved-base")],
    })
    path = tmp_path / "vocabulary_inherited_override_missing_word.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entryOverrides\[0\]\.word must reference a word in the resolved base"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_duplicate_override_across_vocabulary_chain(tmp_path: Path):
    data = _marketing_demo()
    word = data["vocabulary"]["vocabListLong"]["entries"][0]["word"]
    data["vocabulary"]["vocabListEmpty"].update({
        "baseFixture": "vocabListLong",
        "entryOverrides": [_vocabulary_override(word)],
    })
    data["vocabulary"]["vocabListSingle"].update({
        "baseFixture": "vocabListEmpty",
        "entries": [],
        "entryOverrides": [_vocabulary_override(word)],
    })
    path = tmp_path / "vocabulary_duplicate_override_across_chain.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"must not override the same word twice across inheritance"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_dictionary_override_marked_review_eligible(tmp_path: Path):
    data = _marketing_demo()
    word = data["vocabulary"]["vocabListLong"]["entries"][0]["word"]
    data["vocabulary"]["vocabListEmpty"].update({
        "baseFixture": "vocabListLong",
        "entryOverrides": [_vocabulary_override(word, card_role="dictionary", review_eligible=True)],
    })
    path = tmp_path / "vocabulary_dictionary_review_eligible.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"reviewEligible must be false for dictionary cards"):
        validate_fixture_dataset_file(path)


def test_validate_allows_inherited_review_history_for_resolved_base_word(tmp_path: Path):
    data = _marketing_demo()
    word = data["vocabulary"]["vocabListLong"]["entries"][0]["word"]
    data["vocabulary"]["vocabListEmpty"].update({
        "baseFixture": "vocabListLong",
        "reviewHistory": [{"word": word, "feedback": 1, "reviewedAt": "2026-01-01T00:00:00Z"}],
    })
    path = tmp_path / "vocabulary_inherited_review_history.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path) == "marketing_demo"


def test_validate_rejects_review_deck_invalid_action_type(tmp_path: Path):
    data = _marketing_demo()
    data["reviewDeck"]["phaseSingle"]["entries"][0]["actionType"] = "merge"
    path = tmp_path / "review_deck_bad_action_type.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"reviewDeck.phaseSingle.entries\[0\].actionType must be add/delete/edit"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["podcast"]["shelf_continue"]["episodes"][2]["lastPlayedTime"]
    path = tmp_path / "podcast_missing_nullable_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes\[2\] keys .*lastPlayedTime"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_unknown_series_key(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["series"]["legacyCover"] = "cover.png"
    path = tmp_path / "podcast_unknown_series_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.series keys .*legacyCover"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_invalid_color_hex(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["series"]["colorHex"] = "blue"
    path = tmp_path / "podcast_bad_color_hex.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.series.colorHex must be #RRGGBB"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_empty_hosts(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["series"]["hostNames"] = []
    path = tmp_path / "podcast_empty_hosts.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.series.hostNames must not be empty"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_duplicate_episode_numbers(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["episodes"][1]["episodeNumber"] = 1
    path = tmp_path / "podcast_duplicate_episode_numbers.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes.episodeNumber must not contain duplicate values"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_progress_after_duration(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["episodes"][0]["lastPlayedTime"] = 9999
    path = tmp_path / "podcast_progress_after_duration.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes\[0\].lastPlayedTime must not exceed durationSec"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_non_positive_duration(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["episodes"][0]["durationSec"] = 0
    path = tmp_path / "podcast_non_positive_duration.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes\[0\].durationSec must be positive"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["todayReview"]["front"]["currentCard"]["chapterTitle"]
    path = tmp_path / "today_review_missing_nullable_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.currentCard keys .*chapterTitle"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_invalid_reveal_stage(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["revealStage"] = "middle"
    path = tmp_path / "today_review_bad_reveal_stage.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.revealStage is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_autoplay_progress_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["autoplayProgress"] = 1.2
    path = tmp_path / "today_review_bad_autoplay_progress.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.autoplayProgress must be between 0 and 1"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_paused_without_autoplay(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["isAutoPlayPaused"] = True
    path = tmp_path / "today_review_paused_without_autoplay.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.isAutoPlayPaused requires isAutoPlaying=true"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_link_kind_bucket_drift(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["currentCard"]["graphLinksByKind"]["shares_usage"][0]["kind"] = "antonym"
    path = tmp_path / "today_review_link_kind_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"kind must match graphLinksByKind bucket shares_usage"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_link_confidence_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["currentCard"]["graphLinksByKind"]["shares_usage"][0]["confidence"] = 1.5
    path = tmp_path / "today_review_link_confidence_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"confidence must be between 0 and 1"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_completed_session_with_current_card(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["completed"]["currentCard"] = dict(data["todayReview"]["front"]["currentCard"])
    path = tmp_path / "today_review_completed_with_current_card.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.completed completed session must not declare currentCard"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_unknown_key(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["legacyPhase"] = "idle"
    path = tmp_path / "sync_presenter_unknown_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready keys .*legacyPhase"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_phase(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["phase"] = "idle"
    path = tmp_path / "sync_presenter_invalid_phase.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.phase is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_failure_kind_without_failed_phase(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["failureKind"] = "partial"
    path = tmp_path / "sync_presenter_failure_kind_without_failed_phase.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready non-null failureKind requires failed phase"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_pending_count_drift(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingCount"] = 4
    path = tmp_path / "sync_presenter_pending_count_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingCount must equal addCount"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_ready_pending_rows_count_drift(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingRows"].pop()
    path = tmp_path / "sync_presenter_ready_rows_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingRows count must equal pendingCount"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_step_state(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["running"]["steps"][0]["status"] = "queued"
    path = tmp_path / "sync_presenter_invalid_step_state.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.running.steps\[0\].upload_delete.status is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_step_progress_drift(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["running"]["steps"][0]["current"] = 2
    path = tmp_path / "sync_presenter_step_progress_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.running.steps\[0\].current must not exceed total"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_pending_row_uuid(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingRows"][0]["id"] = "not-a-uuid"
    path = tmp_path / "sync_presenter_invalid_row_uuid.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingRows\[0\].id must be UUID"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_pending_row_tone(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingRows"][0]["actionTone"] = "warning"
    path = tmp_path / "sync_presenter_invalid_row_tone.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingRows\[0\].actionTone is invalid"):
        validate_fixture_dataset_file(path)


def test_cli_prints_dataset_id_for_valid_world():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "ui_world_manifest.py"),
            "validate",
            str(ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "marketing_demo"


def _canonical_review_clock():
    return {
        "now": "2026-07-10T23:59:59Z",
        "timeZone": "UTC",
        "frozenEpoch": 1783727999,
        "anchorDay": "2026-07-10",
        "source": "history_plan.anchor_day",
    }


def _canonical_dictionary_context():
    state_rows = {
        state: {
            "fixtureID": f"dictionary.lookup.{state}",
            "stepLabel": state,
        }
        for state in ("idle", "loading", "result", "partial", "offline", "error", "retry")
    }
    return {
        "lookup": state_rows,
        "senses": [
            {
                "id": "sense-1",
                "partOfSpeech": "noun",
                "gloss": "a durable trace",
                "exampleIDs": ["example-1"],
            }
        ],
        "examples": [
            {"id": "example-1", "senseID": "sense-1", "text": "The mark remained."}
        ],
        "provenance": {
            "provider": "fixture",
            "entryID": "mark",
            "sourceLabel": "canonical dictionary fixture",
        },
        "materialization": {
            "status": "ready",
            "selectedSenseID": "sense-1",
            "selectedExampleID": "example-1",
            "sourceFixtureID": "dictionary.lookup.result",
        },
        "coverage": {
            "required": {
                "fixtureIDs": ["dictionary.lookup.result", "dictionary.detail.senses"],
                "stepLabels": ["idle", "loading", "result", "partial", "offline", "error", "retry"],
                "assetIDs": ["catalog_reader_epub"],
            },
            "counterexamples": {
                "fixtureIDs": ["dictionary.lookup.error"],
                "stepLabels": ["error-counterexample"],
                "assetIDs": ["notebook_cover_app_icon"],
            },
        },
    }


def _canonical_surface_contracts(dictionary=None):
    contracts = {
        "explore": {
            "required": [
                {
                    "fixtureID": "loading",
                    "stepLabel": "explore-loading",
                    "index": 0,
                    "assetIDs": ["explore_required"],
                },
                {
                    "fixtureID": "loaded",
                    "stepLabel": "explore-loaded",
                    "index": 1,
                    "assetIDs": ["explore_required"],
                },
                {
                    "fixtureID": "empty",
                    "stepLabel": "explore-empty",
                    "index": 2,
                    "assetIDs": ["explore_required_empty"],
                },
                {
                    "fixtureID": "retry",
                    "stepLabel": "explore-retry",
                    "index": 3,
                    "assetIDs": ["explore_required"],
                },
            ],
            "counterexamples": [
                {
                    "fixtureID": "empty-counterexample",
                    "stepLabel": "explore-empty-counterexample",
                    "index": 4,
                    "assetIDs": ["explore_counterexample_empty"],
                },
                {
                    "fixtureID": "retry-counterexample",
                    "stepLabel": "explore-retry-counterexample",
                    "index": 5,
                    "assetIDs": ["explore_counterexample_retry"],
                },
            ],
        },
        "settings": {
            "required": [
                {
                    "fixtureID": "settings.clean-preferences",
                    "stepLabel": "settings",
                    "index": 0,
                    "assetIDs": [],
                }
            ],
            "counterexamples": [
                {
                    "fixtureID": "settings.reset-counterexample",
                    "stepLabel": "reset-counterexample",
                    "index": 1,
                    "assetIDs": [],
                }
            ],
        },
    }
    if dictionary is None:
        dictionary = _marketing_demo()["scenarioContext"]["dictionary"]
    contracts["dictionary"] = build_p1_dictionary_surface_contract(dictionary)
    return contracts


def _legacy_scenario_context(data: dict, *, review_clock=None) -> dict:
    context = dict(data["scenarioContext"])
    context.pop("dictionary", None)
    context.pop("surfaceContracts", None)
    context["reviewClock"] = review_clock
    return context


def test_validate_accepts_legacy_null_review_clock(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"] = _legacy_scenario_context(data)
    path = tmp_path / "null_review_clock.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path) == "marketing_demo"


def test_validate_accepts_legacy_frozen_now_review_clock(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"] = _legacy_scenario_context(
        data,
        review_clock={
            "frozenNow": "2026-06-15T23:59:59Z",
            "frozenEpoch": 1781567999,
            "anchorDay": "2026-06-15",
            "source": "legacy.fixture",
        },
    )
    path = tmp_path / "legacy_frozen_now_review_clock.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert validate_fixture_dataset_file(path) == "marketing_demo"


@pytest.mark.parametrize("missing_field", ["readerPassage", "wordDetail"])
@pytest.mark.parametrize(
    "review_clock",
    [
        None,
        {
            "frozenNow": "2026-06-15T23:59:59Z",
            "frozenEpoch": 1781567999,
            "anchorDay": "2026-06-15",
            "source": "legacy.fixture",
        },
    ],
)
def test_validate_rejects_legacy_missing_content_even_with_compatible_clock(
    tmp_path: Path, missing_field: str, review_clock,
):
    data = _marketing_demo()
    context = _legacy_scenario_context(data, review_clock=review_clock)
    context[missing_field] = None
    data["scenarioContext"] = context
    path = tmp_path / f"legacy_missing_{missing_field}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=rf"scenarioContext\.{missing_field}.*object"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_null_review_clock_in_canonical_context(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"]["reviewClock"] = None
    path = tmp_path / "canonical_null_review_clock.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"canonical scenarioContext requires reviewClock"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize("missing_key", ["dictionary", "surfaceContracts"])
def test_validate_rejects_partial_canonical_scenario_context(tmp_path: Path, missing_key: str):
    data = _marketing_demo()
    data["scenarioContext"].pop(missing_key)
    path = tmp_path / f"canonical_missing_{missing_key}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"scenarioContext keys.*(extra|missing)"):
        validate_fixture_dataset_file(path)


def test_validate_accepts_canonical_dictionary_clock_and_surface_contracts(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"]["reviewClock"] = _canonical_review_clock()
    dictionary = _canonical_dictionary_context()
    data["scenarioContext"]["dictionary"] = dictionary
    data["scenarioContext"]["surfaceContracts"] = _canonical_surface_contracts(dictionary)
    path = tmp_path / "canonical_dictionary_and_clock.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    validate_fixture_dataset_file(path)


def test_validate_rejects_missing_p1_dictionary_rich_surface_contract(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"]["surfaceContracts"].pop("dictionary", None)
    path = tmp_path / "p1_dictionary_rich_surface_missing.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(
        UIWorldManifestError,
        match=r"surfaceContracts\.dictionary\.required contract is missing",
    ):
        validate_fixture_dataset_file(path)


def test_validate_rejects_dictionary_materialization_sense_example_mismatch(tmp_path: Path):
    data = _marketing_demo()
    dictionary = _canonical_dictionary_context()
    dictionary["materialization"]["selectedSenseID"] = "sense-2"
    data["scenarioContext"]["dictionary"] = dictionary
    path = tmp_path / "dictionary_materialization_mismatch.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"materialization.*(match|correspond)"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_duplicate_dictionary_lookup_selector(tmp_path: Path):
    data = _marketing_demo()
    dictionary = _canonical_dictionary_context()
    dictionary["lookup"]["retry"]["stepLabel"] = dictionary["lookup"]["result"]["stepLabel"]
    data["scenarioContext"]["dictionary"] = dictionary
    path = tmp_path / "dictionary_lookup_duplicate_selector.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"dictionary\.lookup\.stepLabel.*唯一"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize(
    ("status", "selected_sense", "selected_example"),
    [
        ("pending", "sense-1", "example-1"),
        ("ready", None, None),
    ],
)
def test_validate_rejects_dictionary_materialization_selection_state_contradiction(
    tmp_path: Path, status: str, selected_sense: str | None, selected_example: str | None,
):
    data = _marketing_demo()
    dictionary = _canonical_dictionary_context()
    materialization = dictionary["materialization"]
    materialization["status"] = status
    materialization["selectedSenseID"] = selected_sense
    materialization["selectedExampleID"] = selected_example
    data["scenarioContext"]["dictionary"] = dictionary
    path = tmp_path / f"dictionary_materialization_{status}_contradiction.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"materialization.*status"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize("surface", ["explore", "settings"])
def test_validate_rejects_missing_required_surface_contract(tmp_path: Path, surface: str):
    data = _marketing_demo()
    contracts = _canonical_surface_contracts()
    del contracts[surface]
    data["scenarioContext"]["surfaceContracts"] = contracts
    path = tmp_path / f"surface_contract_missing_{surface}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=rf"surfaceContracts.*{surface}.*required"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_empty_required_surface_selector(tmp_path: Path):
    data = _marketing_demo()
    contracts = _canonical_surface_contracts()
    contracts["explore"]["required"] = []
    data["scenarioContext"]["surfaceContracts"] = contracts
    path = tmp_path / "surface_contract_empty_required.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"surfaceContracts\.explore\.required.*non-empty"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize("field", ["index", "stepLabel"])
def test_validate_rejects_duplicate_surface_selector(tmp_path: Path, field: str):
    data = _marketing_demo()
    contracts = _canonical_surface_contracts()
    duplicate = dict(contracts["explore"]["required"][0])
    duplicate["fixtureID"] = f"explore.duplicate.{field}"
    duplicate["stepLabel"] = f"duplicate-{field}"
    duplicate["assetIDs"] = []
    if field == "index":
        duplicate["index"] = contracts["explore"]["required"][0]["index"]
    else:
        duplicate["stepLabel"] = contracts["explore"]["required"][0]["stepLabel"]
    contracts["explore"]["required"].append(duplicate)
    data["scenarioContext"]["surfaceContracts"] = contracts
    path = tmp_path / f"surface_contract_duplicate_{field}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=rf"surfaceContracts\.explore\.required.*{field}.*unique"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize("owner", ["dictionary", "surface"])
def test_validate_rejects_unknown_asset_id(tmp_path: Path, owner: str):
    data = _marketing_demo()
    if owner == "dictionary":
        dictionary = _canonical_dictionary_context()
        dictionary["coverage"]["required"]["assetIDs"] = ["missing_asset"]
        data["scenarioContext"]["dictionary"] = dictionary
    else:
        contracts = _canonical_surface_contracts()
        contracts["explore"]["required"][0]["assetIDs"] = ["missing_asset"]
        data["scenarioContext"]["surfaceContracts"] = contracts
    path = tmp_path / f"{owner}_unknown_asset_id.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assetIDs references unknown assets"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_asset_id_mapped_to_multiple_asset_types(tmp_path: Path):
    data = _marketing_demo()
    duplicate = dict(data["assets"]["books"]["catalog_reader_epub"])
    data["assets"]["images"]["catalog_reader_epub"] = duplicate
    path = tmp_path / "asset_id_multiple_types.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"asset ID .*one asset type"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_empty_asset_manifest_key(tmp_path: Path):
    data = _marketing_demo()
    empty_key_asset = dict(data["assets"]["images"]["notebook_cover_app_icon"])
    empty_key_asset["installAs"] = "Assets/empty-key.png"
    data["assets"]["images"]["   "] = empty_key_asset
    path = tmp_path / "empty_asset_manifest_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.images\..*key 必須是非空字串"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize("owner", ["dictionary", "surface"])
def test_validate_rejects_legacy_generic_asset_inodes_wire(tmp_path: Path, owner: str):
    data = _marketing_demo()
    if owner == "dictionary":
        data["scenarioContext"]["dictionary"]["coverage"]["required"]["assetInodes"] = [
            "inode:catalog_reader_epub"
        ]
    else:
        data["scenarioContext"]["surfaceContracts"]["explore"]["required"][0]["assetInodes"] = [
            "inode:explore_required"
        ]
    path = tmp_path / f"legacy_generic_asset_inodes_{owner}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assetInodes"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_dictionary_required_counterexample_overlap(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"]["reviewClock"] = _canonical_review_clock()
    dictionary = _canonical_dictionary_context()
    dictionary["coverage"]["counterexamples"]["stepLabels"] = ["loading"]
    data["scenarioContext"]["dictionary"] = dictionary
    path = tmp_path / "dictionary_coverage_overlap.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"dictionary.*stepLabels.*disjoint"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize(
    ("field", "overlap_value"),
    [
        ("fixtureIDs", "dictionary.lookup.result"),
        ("assetIDs", "catalog_reader_epub"),
    ],
)
def test_validate_rejects_dictionary_coverage_overlap_for_each_identity_set(
    tmp_path: Path, field: str, overlap_value: str,
):
    data = _marketing_demo()
    dictionary = _canonical_dictionary_context()
    data["scenarioContext"]["reviewClock"] = _canonical_review_clock()
    dictionary["coverage"]["counterexamples"][field] = [overlap_value]
    data["scenarioContext"]["dictionary"] = dictionary
    path = tmp_path / f"dictionary_{field}_overlap.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=rf"dictionary.*{field}.*disjoint"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_review_clock_history_day_mismatch(tmp_path: Path):
    data = _marketing_demo()
    data["scenarioContext"]["reviewClock"] = _canonical_review_clock()
    data["vocabulary"]["reviewCalendarDense"]["reviewHistory"][0]["reviewedAt"] = (
        "2026-07-11T00:00:00Z"
    )
    path = tmp_path / "review_clock_history_mismatch.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"reviewClock.*reviewHistory"):
        validate_fixture_dataset_file(path)
