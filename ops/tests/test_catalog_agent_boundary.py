from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


LEGACY_CATALOG_PATHS = (
    "ios/BooksAndVocab.xcodeproj/xcshareddata/xcschemes/BooksAndVocabCatalogSnapshots.xcscheme",
    "ios/BooksAndVocab/Debug/CatalogGraphSnapshotFreezer.swift",
    "ios/BooksAndVocabTests/CatalogCoverageTests.swift",
    "ios/BooksAndVocabTests/CatalogSnapshotTests.swift",
    "ops/capture_profile.py",
    "ops/capture_profiles",
    "ops/catalog_appearance_proof.py",
    "ops/catalog_contact_sheet.py",
    "ops/catalog_png_inspect.swift",
    "ops/catalog_review_actions.py",
    "ops/catalog_review_cli.py",
    "ops/catalog_review_cli_artifacts.py",
    "ops/catalog_review_cli_filters.py",
    "ops/catalog_review_cli_maintenance.py",
    "ops/catalog_review_cli_mutations.py",
    "ops/catalog_review_cli_parser.py",
    "ops/catalog_review_cli_queries.py",
    "ops/catalog_review_cli_query_model.py",
    "ops/catalog_review_cli_serialization.py",
    "ops/catalog_review_doctor.py",
    "ops/catalog_review_entry.py",
    "ops/catalog_review_focus.py",
    "ops/catalog_review_manifest.py",
    "ops/catalog_review_profile.json",
    "ops/catalog_review_profile.py",
    "ops/catalog_review_renderer.py",
    "ops/catalog_review_repair.py",
    "ops/catalog_review_report.py",
    "ops/catalog_review_state.py",
    "ops/catalog_review_sync.py",
    "ops/catalog_review_taxonomy.py",
    "ops/catalog_review_verify.py",
    "ops/render_catalog_review.py",
    "ops/reviewer_evidence.py",
    "promotion/screenshots",
)


def test_legacy_gallery_snapshot_and_marketing_renderers_are_removed() -> None:
    remaining = []
    for path in LEGACY_CATALOG_PATHS:
        candidate = ROOT / path
        if candidate.is_file() or (candidate.is_dir() and any(item.is_file() for item in candidate.rglob("*"))):
            remaining.append(path)
    assert remaining == []


def test_catalog_is_not_a_snapshot_or_visual_regression_gate() -> None:
    quality_plane = (ROOT / "ops/ui_quality_plane.yml").read_text(encoding="utf-8")
    assert "snapshot.catalog" not in quality_plane
    assert "visual.catalog_regression" not in quality_plane
    assert "CatalogCoverageTests" not in quality_plane


def test_playbook_snapshot_is_not_linked() -> None:
    project = (ROOT / "ios/BooksAndVocab.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    assert "PlaybookSnapshot" not in project


def test_catalog_cli_is_an_agent_tool_not_an_export_pipeline() -> None:
    source = (ROOT / "ops/lib/ios_ops_catalog.sh").read_text(encoding="utf-8")
    for action in ("catalog list", "catalog open", "catalog capture", "catalog close"):
        assert action in source
    assert "simctl io" in source
    assert "screenshot" in source
    assert 'renderer:"simulator-window"' in source
    for legacy in ("contact sheet", "gallery", "marketing images", "xcodebuild test-without-building"):
        assert legacy not in source.lower()


def test_catalog_scene_has_no_coverage_taxonomy_or_snapshot_renderer() -> None:
    source = (ROOT / "ios/BooksAndVocab/Debug/CatalogScene.swift").read_text(encoding="utf-8")
    for legacy in (
        "SurfaceKind",
        "ScreenID",
        "CatalogSurface",
        "pendingCoverage",
        "indexJSONData",
        "CatalogCoverageTests",
        "PlaybookSnapshot",
    ):
        assert legacy not in source
    assert "CatalogAgentContract" in source
    assert "ScenarioViewController" in source


def test_catalog_is_simulator_only_at_the_app_entrypoint() -> None:
    source = (ROOT / "ios/BooksAndVocab/BooksAndVocabApp.swift").read_text(encoding="utf-8")
    assert "#if DEBUG && targetEnvironment(simulator) && canImport(Playbook)" in source
