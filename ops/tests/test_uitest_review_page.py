from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"


def _load():
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    spec = importlib.util.spec_from_file_location(
        "uitest_review_page", ROOT / "ops" / "uitest_review_page.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _png(path: Path):
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 8
        + (120).to_bytes(4, "big")
        + (240).to_bytes(4, "big")
    )


def _manifest(root: Path) -> Path:
    manifest = {
        "schema": "kg.visual-review.sheet.v1",
        "source": "uitest",
        "items": [
            {
                "assetID": "01-launch",
                "relPath": "01-launch.png",
                "surface": "AuthFlowUITests",
                "stateLabel": "launch",
                "appearance": "light",
            },
            {
                "assetID": "02-player",
                "relPath": "02-player.png",
                "surface": "AuthFlowUITests",
                "stateLabel": "player",
                "appearance": "light",
            },
        ],
    }
    path = root / "review_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_build_review_root_updates_workspace_index(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    _png(steps / "02-player.png")
    manifest = _manifest(steps)
    video = tmp_path / "20260614-010203-ui.mp4"
    video.write_bytes(b"video")
    log = tmp_path / "test.log"
    log.write_text("KG_PERF play.started\n", encoding="utf-8")
    out_root = tmp_path / "build" / "snapshots" / "uitest-runs" / "20260614-010203-ui"

    payload = mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        contact_sheet=None,
        quick4_sheet=None,
        video=video,
        out_root=out_root,
        log=log,
        flow_id="auth_flow",
        variant_id="free_preview",
        status="ok",
        test_file="AuthFlowUITests.swift",
        device="STUB-UDID",
        last_run_at="2026-06-14T01:02:03+00:00",
    )

    workspace_root = out_root.parent
    workspace_index = json.loads((workspace_root / "index.json").read_text(encoding="utf-8"))
    assert payload["workspace"]["html"] == str(workspace_root / "UIreview.html")
    assert workspace_index["schema"] == "kg.ios.uitest-review-workspace.v1"
    assert workspace_index["summary"]["totalRuns"] == 1
    assert workspace_index["summary"]["okRuns"] == 1
    run = workspace_index["runs"][0]
    assert run["flowId"] == "auth_flow"
    assert run["variantId"] == "free_preview"
    assert run["lastRunAt"] == "2026-06-14T01:02:03+00:00"
    assert run["artifacts"]["reviewHtml"] == "20260614-010203-ui/UIreview.html"
    assert run["artifacts"]["video"] == "20260614-010203-ui/uitest-videos/20260614-010203-ui.mp4"
    assert run["artifacts"]["log"] == "20260614-010203-ui/test.log"
    run_html = (out_root / "UIreview.html").read_text(encoding="utf-8")
    assert "KG UITest Run Review" in run_html
    assert "2026-06-14T01:02:03+00:00" in run_html
    assert "uitest-videos/20260614-010203-ui.mp4" in run_html
    assert "20260614-010203-ui/uitest-videos/20260614-010203-ui.mp4" not in run_html
    assert "test.log" in run_html
    assert "review_manifest.json" in run_html
    assert "01-launch.png" in run_html
    assert "02-player.png" in run_html

    newer_out_root = tmp_path / "build" / "snapshots" / "uitest-runs" / "20260614-020304-ui"
    mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        contact_sheet=None,
        quick4_sheet=None,
        video=video,
        out_root=newer_out_root,
        log=log,
        flow_id="auth_flow",
        variant_id="free_preview",
        status="fail",
        test_file="AuthFlowUITests.swift",
        device="STUB-UDID",
        last_run_at="2026-06-14T02:03:04+00:00",
    )

    replaced = json.loads((workspace_root / "index.json").read_text(encoding="utf-8"))
    assert replaced["summary"]["totalRuns"] == 1
    assert replaced["summary"]["okRuns"] == 0
    assert replaced["summary"]["failRuns"] == 1
    assert replaced["runs"][0]["runId"] == "20260614-020304-ui"
    assert replaced["runs"][0]["lastRunAt"] == "2026-06-14T02:03:04+00:00"


def test_workspace_html_links_runs_and_artifacts(tmp_path):
    mod = _load()
    workspace_root = tmp_path / "uitest-runs"
    run_root = workspace_root / "run-a"
    run_root.mkdir(parents=True)
    (run_root / "UIreview.html").write_text("<html>run</html>", encoding="utf-8")
    (run_root / "test.log").write_text("log", encoding="utf-8")
    index = {
        "schema": "kg.ios.uitest-review-workspace.v1",
        "summary": {"totalRuns": 1, "okRuns": 0, "failRuns": 1, "flows": 1, "variants": 1},
        "runs": [
            {
                "runId": "run-a",
                "flowId": "settings_flow",
                "variantId": "guest",
                "status": "fail",
                "lastRunAt": "2026-06-14T03:04:05+00:00",
                "testFile": "SettingsFlowUITests.swift",
                "device": "SIM-1",
                "artifacts": {
                    "reviewHtml": "run-a/UIreview.html",
                    "log": "run-a/test.log",
                    "video": "run-a/uitest-videos/run-a.mp4",
                },
                "steps": [{"assetID": "01-launch", "stateLabel": "launch"}],
            }
        ],
        "flows": [
            {
                "flowId": "settings_flow",
                "runs": 1,
                "latestStatus": "fail",
                "lastRunAt": "2026-06-14T03:04:05+00:00",
                "variants": ["guest"],
            }
        ],
    }

    html = mod.render_workspace_html(index)

    assert "settings_flow" in html
    assert "SettingsFlowUITests.swift" in html
    assert "2026-06-14T03:04:05+00:00" in html
    assert "run-a/UIreview.html" in html
    assert "run-a/test.log" in html
    assert "run-a/uitest-videos/run-a.mp4" in html


def test_workspace_html_lists_pending_flows_without_runs(tmp_path):
    mod = _load()
    test_root = tmp_path / "ios" / "BooksAndVocabUITests"
    test_root.mkdir(parents=True)
    (test_root / "OverviewFlowUITests.swift").write_text(
        """
        import XCTest
        final class OverviewFlowUITests: XCTestCase {
            func testOverviewStatsRenderFromSeededReviewHistory() throws {}
        }
        """,
        encoding="utf-8",
    )
    (test_root / "SettingsFlowUITests.swift").write_text(
        """
        import XCTest
        final class SettingsFlowUITests: XCTestCase {
            func testSettingsRowsNavigate() throws {}
            func helperIsNotATest() {}
        }
        """,
        encoding="utf-8",
    )
    workspace_root = tmp_path / "build" / "snapshots" / "uitest-runs"

    payload = mod.ensure_workspace(
        workspace_root=workspace_root,
        test_root=test_root,
        project_root=tmp_path,
    )

    index = json.loads((workspace_root / "index.json").read_text(encoding="utf-8"))
    html = (workspace_root / "UIreview.html").read_text(encoding="utf-8")
    assert payload["summary"]["totalRuns"] == 0
    assert payload["summary"]["flows"] == 2
    assert payload["summary"]["pendingFlows"] == 2
    assert index["flows"][0]["latestStatus"] == "never-run"
    assert "Flow Inventory" in html
    assert 'class="tabs"' in html
    assert 'data-filter="pending"' in html
    assert 'class="table-wrap"' in html
    assert 'id="search"' in html
    assert 'class="flow-row"' in html
    assert 'class="flow-card status-pending"' in html
    assert "OverviewFlowUITests" in html
    assert "SettingsFlowUITests" in html
    assert "never-run" in html
    assert "./ops/ios_ops.sh test --ui --file OverviewFlowUITests.swift --lease --json" in html
    assert "testOverviewStatsRenderFromSeededReviewHistory" in html
    assert "testSettingsRowsNavigate" in html


def test_workspace_preserves_run_and_marks_only_missing_flows_pending(tmp_path):
    mod = _load()
    test_root = tmp_path / "ios" / "BooksAndVocabUITests"
    test_root.mkdir(parents=True)
    (test_root / "OverviewFlowUITests.swift").write_text(
        "final class OverviewFlowUITests { func testOverview() throws {} }\n",
        encoding="utf-8",
    )
    (test_root / "SettingsFlowUITests.swift").write_text(
        "final class SettingsFlowUITests { func testSettings() throws {} }\n",
        encoding="utf-8",
    )
    workspace_root = tmp_path / "build" / "snapshots" / "uitest-runs"
    index = {
        "schema": "kg.ios.uitest-review-workspace.v1",
        "summary": {"totalRuns": 1, "okRuns": 1, "failRuns": 0, "flows": 1, "variants": 1},
        "runs": [
            {
                "runId": "run-a",
                "flowId": "OverviewFlowUITests",
                "variantId": "default",
                "status": "ok",
                "lastRunAt": "2026-06-14T03:04:05+00:00",
                "testFile": "OverviewFlowUITests.swift",
                "device": "SIM-1",
                "stepCount": 2,
                "artifacts": {"reviewHtml": "run-a/UIreview.html"},
            }
        ],
        "flows": [],
    }
    workspace_root.mkdir(parents=True)
    (workspace_root / "index.json").write_text(json.dumps(index), encoding="utf-8")

    payload = mod.ensure_workspace(
        workspace_root=workspace_root,
        test_root=test_root,
        project_root=tmp_path,
    )

    flows = {flow["flowId"]: flow for flow in payload["flows"]}
    assert payload["summary"]["totalRuns"] == 1
    assert payload["summary"]["flows"] == 2
    assert payload["summary"]["pendingFlows"] == 1
    assert flows["OverviewFlowUITests"]["latestStatus"] == "ok"
    assert flows["SettingsFlowUITests"]["latestStatus"] == "never-run"


def test_run_html_supports_zero_step_runs(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    manifest = steps / "review_manifest.json"
    manifest.write_text(
        json.dumps({"schema": "kg.visual-review.sheet.v1", "source": "uitest", "items": []}),
        encoding="utf-8",
    )
    video = tmp_path / "20260614-040506-ui.mp4"
    video.write_bytes(b"video")
    log = tmp_path / "test.log"
    log.write_text("launch smoke log\n", encoding="utf-8")
    out_root = tmp_path / "build" / "snapshots" / "uitest-runs" / "20260614-040506-ui"

    mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        contact_sheet=None,
        quick4_sheet=None,
        video=video,
        out_root=out_root,
        log=log,
        flow_id="launch_smoke",
        variant_id="default",
        status="ok",
        test_file="LaunchUITests.swift",
        device="STUB-UDID",
        last_run_at="2026-06-14T04:05:06+00:00",
    )

    html = (out_root / "UIreview.html").read_text(encoding="utf-8")
    assert "No step screenshots were emitted for this UITest run." in html
    assert "2026-06-14T04:05:06+00:00" in html
    assert "uitest-videos/20260614-040506-ui.mp4" in html
    assert "20260614-040506-ui/uitest-videos/20260614-040506-ui.mp4" not in html
    assert "test.log" in html
    assert "review_manifest.json" in html
    assert "contact sheets missing" in html
