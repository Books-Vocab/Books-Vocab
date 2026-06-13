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
    assert run["artifacts"]["reviewHtml"] == "20260614-010203-ui/UIreview.html"
    assert run["artifacts"]["video"] == "20260614-010203-ui/uitest-videos/20260614-010203-ui.mp4"
    assert run["artifacts"]["log"] == "20260614-010203-ui/test.log"


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
                "variants": ["guest"],
            }
        ],
    }

    html = mod.render_workspace_html(index)

    assert "settings_flow" in html
    assert "SettingsFlowUITests.swift" in html
    assert "run-a/UIreview.html" in html
    assert "run-a/test.log" in html
    assert "run-a/uitest-videos/run-a.mp4" in html
