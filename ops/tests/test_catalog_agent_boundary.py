from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess


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


def test_retired_gallery_launchers_are_removed() -> None:
    launch = (ROOT / ".claude/launch.json").read_text(encoding="utf-8")
    for legacy in ("ui-asset-gallery", "gallery-admin", "catalog_review_entry.py"):
        assert legacy not in launch


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
    assert "Duplicate Catalog scenario IDs" in source


def test_catalog_is_simulator_only_at_the_app_entrypoint() -> None:
    source = (ROOT / "ios/BooksAndVocab/BooksAndVocabApp.swift").read_text(encoding="utf-8")
    assert "#if DEBUG && targetEnvironment(simulator) && canImport(Playbook)" in source


def test_ui_world_has_no_marketing_capture_domain() -> None:
    paths = (
        "ops/ui_world_manifest.py",
        "ops/demo/emit_ios.py",
        "ops/demo/spec_world.py",
        "ops/fixtures/ui_worlds/marketing_demo.json",
        "ops/demo/generated/ios_fixture_dataset.json",
        "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift",
        "ios/BooksAndVocabTests/RepoFixtureDatasetsContractTests.swift",
        "ios/BooksAndVocab/Debug/Scenarios/WordDetailScenarios.swift",
        "ios/BooksAndVocab/Views/Reader/ReaderViewPresenter+Preview.swift",
    )
    offenders = {
        path: token
        for path in paths
        for token in ("marketingCapture", "MarketingCapture", "MarketingReviewClock")
        if token in (ROOT / path).read_text(encoding="utf-8")
    }
    assert offenders == {}


def test_ui_world_scenario_context_is_optional() -> None:
    source = (ROOT / "ops/ui_world_manifest.py").read_text(encoding="utf-8")
    assert 'OPTIONAL_TOP_LEVEL_KEYS = {"scenarioContext"}' in source


def test_retired_app_review_renderer_contract_is_absent() -> None:
    source = (ROOT / "ops/app_review_gate.py").read_text(encoding="utf-8")
    for token in (
        "capture-profile",
        "promotion-closure",
        "render-spec",
        "promotionManifest",
        "renderSpec",
        "capture_profile",
        "reviewer_evidence",
    ):
        assert token not in source


def test_catalog_session_lifecycle_checks_live_lease_ownership_and_cleans_start_failures() -> None:
    source = (ROOT / "ops/lib/ios_ops_catalog.sh").read_text(encoding="utf-8")
    assert "catalog_assert_session_ownership" in source
    assert "catalog_abort_active_session" in source
    assert "trap 'catalog_abort_active_session' EXIT" in source
    assert "simctl erase" in source
    assert "KG_IOS_CATALOG_BOOT_TIMEOUT:-300" in source
    assert "KG_IOS_CATALOG_BUILD_TIMEOUT:-900" in source
    assert 'disown "$CATALOG_ACTIVE_KEEPER_PID"' in source
    assert "SIM_LEASE_SKIP_BOOT=1 cmd_simulator_lease --json" in source
    assert 'release_status="$(jq -r \'.status\' <<<"$release_json")"' in source
    assert '[[ "$release_status" == "ok" ]]' in source


def _catalog_shell_prelude(tmp_path: Path, session: str, owner_token: str) -> tuple[str, Path, Path]:
    session_root = tmp_path / "sessions"
    lease_root = tmp_path / "leases"
    lease_dir = lease_root / "lease-1"
    log = tmp_path / "xcrun.log"
    session_root.mkdir()
    lease_dir.mkdir(parents=True)
    (lease_dir / "udid").write_text("SIM-1\n", encoding="utf-8")
    (lease_dir / "owner_token").write_text(f"{owner_token}\n", encoding="utf-8")
    state = {
        "session": session,
        "udid": "SIM-1",
        "ownerToken": session,
        "leaseDir": str(lease_dir),
        "keeperPid": "",
    }
    (session_root / f"{session}.json").write_text(json.dumps(state), encoding="utf-8")
    script = f"""
ROOT={shlex.quote(str(ROOT))}
SIM_LEASE_ROOT={shlex.quote(str(lease_root))}
BUNDLE_ID=com.example.CatalogTest
KG_IOS_CATALOG_SESSION_ROOT={shlex.quote(str(session_root))}
export KG_IOS_CATALOG_SESSION_ROOT
source {shlex.quote(str(ROOT / 'ops/lib/ios_ops_catalog.sh'))}
xcrun() {{ printf '%s\\n' "$*" >> {shlex.quote(str(log))}; return 0; }}
"""
    return script, session_root / f"{session}.json", log


def test_stale_catalog_session_refuses_capture_before_touching_simulator(tmp_path: Path) -> None:
    session = "catalog-stale"
    script, state, log = _catalog_shell_prelude(tmp_path, session, owner_token="new-owner")
    script += f"""
if catalog_capture --session {session} --out {shlex.quote(str(tmp_path / 'shot.png'))}; then
  exit 80
fi
[[ -f {shlex.quote(str(state))} ]] || exit 81
[[ ! -s {shlex.quote(str(log))} ]] || exit 82
"""

    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr


def test_catalog_close_keeps_state_when_lease_release_refuses(tmp_path: Path) -> None:
    session = "catalog-noop"
    script, state, _log = _catalog_shell_prelude(tmp_path, session, owner_token=session)
    script += f"""
cmd_simulator_release() {{ printf '%s\\n' '{{"status":"noop","error":"owner-token-mismatch"}}'; }}
if catalog_release_session {session}; then
  exit 80
fi
[[ -f {shlex.quote(str(state))} ]] || exit 81
"""

    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr


def test_catalog_close_disarms_abort_trap_before_emitting_response(tmp_path: Path) -> None:
    session = "catalog-closed"
    script, state, log = _catalog_shell_prelude(tmp_path, session, owner_token=session)
    script += f"""
cmd_simulator_release() {{ printf '%s\\n' '{{"status":"ok"}}'; }}
catalog_emit() {{ return 77; }}
set -e
catalog_close --session {session}
"""

    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)

    assert result.returncode == 77, result.stderr
    assert not state.exists()
    assert log.read_text(encoding="utf-8").count("simctl erase SIM-1") == 1


def test_catalog_start_trap_erases_and_releases_owned_simulator(tmp_path: Path) -> None:
    session = "catalog-abort"
    script, state, log = _catalog_shell_prelude(tmp_path, session, owner_token=session)
    script += f"""
cmd_simulator_release() {{ printf '%s\\n' '{{"status":"ok"}}'; }}
(
  CATALOG_ACTIVE_SESSION={session}
  CATALOG_ACTIVE_UDID=SIM-1
  catalog_arm_cleanup
  exit 41
)
[[ $? -eq 41 ]] || exit 80
[[ ! -f {shlex.quote(str(state))} ]] || exit 81
grep -q 'simctl erase SIM-1' {shlex.quote(str(log))} || exit 82
"""

    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
