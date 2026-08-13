from __future__ import annotations

import importlib.util
import json
import sys
import hashlib
import subprocess
import struct
import time
import zlib
from pathlib import Path

import pytest


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
    width, height = 120, 240
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\xff\x00\x00" * width
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _manifest(root: Path) -> Path:
    items = []
    for path in sorted(root.glob("*.png")):
        data = path.read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        items.append(
            {
                "assetID": path.stem,
                "relPath": path.name,
                "surface": "AuthFlowUITests",
                "stateLabel": path.stem,
                "appearance": "light",
                "width": width,
                "height": height,
                "byteSize": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "schema": "kg.visual-review.sheet.v1",
        "source": "uitest",
        "items": items,
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

    history = json.loads((workspace_root / "index.json").read_text(encoding="utf-8"))
    assert history["summary"]["totalRuns"] == 2
    assert history["summary"]["okRuns"] == 1
    assert history["summary"]["failRuns"] == 1
    assert history["runs"][0]["runId"] == "20260614-020304-ui"
    assert history["runs"][1]["runId"] == "20260614-010203-ui"


def test_workspace_concurrent_writers_preserve_complete_history(tmp_path):
    workspace_root = tmp_path / "uitest-runs"
    test_root = tmp_path / "empty-tests"
    test_root.mkdir()
    writer_count = 16
    writes_per_writer = 5
    start_at = time.time() + 1.0
    writer = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import uitest_review_workspace as workspace
root = Path(sys.argv[2])
test_root = Path(sys.argv[3])
writer_id = int(sys.argv[4])
start_at = float(sys.argv[5])
for sequence in range(5):
    target = start_at + sequence * 0.15
    while time.time() < target:
        time.sleep(0.001)
    workspace.write_workspace_index(
        root,
        {
            "runId": f"writer-{writer_id}-run-{sequence}",
            "flowId": f"flow-{writer_id}",
            "variantId": "default",
            "status": "ok",
            "lastRunAt": f"2026-08-13T00:{writer_id:02d}:{sequence:02d}+00:00",
            "testFile": f"Flow{writer_id}UITests.swift",
            "device": f"SIM-{writer_id}",
            "stepCount": 1,
            "artifacts": {},
        },
        test_root=test_root,
        project_root=root.parent,
    )
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                writer,
                str(ROOT / "ops"),
                str(workspace_root),
                str(test_root),
                str(writer_id),
                str(start_at),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for writer_id in range(writer_count)
    ]

    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            failures.append((process.returncode, stdout, stderr))
    assert failures == []

    index = json.loads((workspace_root / "index.json").read_text(encoding="utf-8"))
    expected_count = writer_count * writes_per_writer
    assert len(index["runs"]) == expected_count
    assert len({run["runId"] for run in index["runs"]}) == expected_count
    assert index["summary"]["totalRuns"] == expected_count
    assert list(workspace_root.glob(".*.tmp")) == []


def test_review_root_publication_failure_cleans_orphan_and_allows_retry(
    tmp_path, monkeypatch
):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    manifest = _manifest(steps)
    video = tmp_path / "flow.mp4"
    video.write_bytes(b"video")
    out_root = tmp_path / "uitest-runs" / "run-retry"
    original_write_workspace_index = mod.write_workspace_index

    def fail_workspace_publish(*_args, **_kwargs):
        raise mod.WorkspacePublicationError(
            "injected workspace publication failure", committed=False
        )

    monkeypatch.setattr(mod, "write_workspace_index", fail_workspace_publish)
    with pytest.raises(OSError, match="injected workspace publication failure"):
        mod.build_review_root(
            screenshot_dir=steps,
            manifest_path=manifest,
            contact_sheet=None,
            quick4_sheet=None,
            video=video,
            out_root=out_root,
            flow_id="retry_flow",
            status="fail",
        )

    assert not out_root.exists()
    assert list(out_root.parent.glob(".run-retry.staging.*")) == []

    monkeypatch.setattr(mod, "write_workspace_index", original_write_workspace_index)
    payload = mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        contact_sheet=None,
        quick4_sheet=None,
        video=video,
        out_root=out_root,
        flow_id="retry_flow",
        status="fail",
    )
    assert Path(payload["html"]).is_file()
    index = json.loads((out_root.parent / "index.json").read_text(encoding="utf-8"))
    assert [run["runId"] for run in index["runs"]] == ["run-retry"]


@pytest.mark.parametrize(
    ("failure_point", "committed"),
    [
        ("before-html-replace", False),
        ("after-html-replace", False),
        ("before-index-replace", False),
        ("after-index-replace", True),
        ("after-index-directory-fsync", True),
    ],
)
def test_workspace_publication_faults_preserve_transaction_boundary(
    tmp_path, monkeypatch, failure_point, committed
):
    mod = _load()
    workspace = sys.modules["uitest_review_workspace"]
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    manifest = _manifest(steps)
    video = tmp_path / "flow.mp4"
    video.write_bytes(b"video")
    workspace_root = tmp_path / "uitest-runs"

    first_root = workspace_root / "run-existing"
    mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        contact_sheet=None,
        quick4_sheet=None,
        video=video,
        out_root=first_root,
        flow_id="existing-flow",
        status="ok",
        last_run_at="2026-08-13T00:00:00+00:00",
    )
    old_html = (workspace_root / "UIreview.html").read_bytes()
    old_index = (workspace_root / "index.json").read_bytes()

    original_atomic_write = workspace._atomic_write_text
    write_calls = 0
    injected = False

    def faulting_atomic_write(path, content):
        nonlocal write_calls, injected
        write_calls += 1
        target_call = 1 if "html" in failure_point else 2
        if write_calls == target_call and failure_point.startswith("before-"):
            injected = True
            raise OSError(f"injected {failure_point}")
        original_atomic_write(path, content)

    monkeypatch.setattr(workspace, "_atomic_write_text", faulting_atomic_write)

    if failure_point in {"after-html-replace", "after-index-replace"}:
        replace_calls = 0

        def faulting_after_replace(_path):
            nonlocal replace_calls, injected
            replace_calls += 1
            target_call = 1 if "html" in failure_point else 2
            if replace_calls == target_call:
                injected = True
                raise OSError(f"injected {failure_point}")

        monkeypatch.setattr(
            workspace, "_after_atomic_replace", faulting_after_replace, raising=False
        )
    elif failure_point == "after-index-directory-fsync":
        directory_fsync_calls = 0

        def faulting_directory_fsync(_directory):
            nonlocal directory_fsync_calls, injected
            directory_fsync_calls += 1
            if directory_fsync_calls == 2:
                injected = True
                raise OSError(f"injected {failure_point}")

        # The dedicated seam makes the post-index durability boundary
        # deterministic without monkeypatching process-wide os.fsync.
        monkeypatch.setattr(
            workspace, "_fsync_directory", faulting_directory_fsync, raising=False
        )

    new_root = workspace_root / f"run-{failure_point}"
    with pytest.raises(OSError, match=f"injected {failure_point}") as error:
        mod.build_review_root(
            screenshot_dir=steps,
            manifest_path=manifest,
            contact_sheet=None,
            quick4_sheet=None,
            video=video,
            out_root=new_root,
            flow_id="new-flow",
            status="fail",
            last_run_at="2026-08-13T00:01:00+00:00",
        )

    assert injected is True
    assert getattr(error.value, "committed", None) is committed
    index = json.loads((workspace_root / "index.json").read_text(encoding="utf-8"))
    run_ids = [run["runId"] for run in index["runs"]]
    if committed:
        assert new_root.is_dir()
        assert new_root.name in run_ids
        assert (workspace_root / "UIreview.html").read_bytes() != old_html
        assert (workspace_root / "index.json").read_bytes() != old_index
    else:
        assert not new_root.exists()
        assert run_ids == ["run-existing"]
        assert (workspace_root / "UIreview.html").read_bytes() == old_html
        assert (workspace_root / "index.json").read_bytes() == old_index
        retry = mod.build_review_root(
            screenshot_dir=steps,
            manifest_path=manifest,
            contact_sheet=None,
            quick4_sheet=None,
            video=video,
            out_root=new_root,
            flow_id="new-flow",
            status="fail",
            last_run_at="2026-08-13T00:01:00+00:00",
        )
        assert Path(retry["html"]).is_file()
        retried_index = json.loads(
            (workspace_root / "index.json").read_text(encoding="utf-8")
        )
        assert new_root.name in [run["runId"] for run in retried_index["runs"]]


def test_workspace_rollback_failure_preserves_run_and_original_error_evidence(
    tmp_path, monkeypatch
):
    mod = _load()
    workspace = sys.modules["uitest_review_workspace"]
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    manifest = _manifest(steps)
    video = tmp_path / "flow.mp4"
    video.write_bytes(b"video")
    workspace_root = tmp_path / "uitest-runs"

    existing_root = workspace_root / "run-existing"
    mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        contact_sheet=None,
        quick4_sheet=None,
        video=video,
        out_root=existing_root,
        flow_id="existing-flow",
        status="ok",
        last_run_at="2026-08-13T00:00:00+00:00",
    )
    old_index = (workspace_root / "index.json").read_bytes()
    old_html = (workspace_root / "UIreview.html").read_bytes()

    original_atomic_write = workspace._atomic_write_text
    write_calls = 0

    def fail_index_then_html_rollback(path, content):
        nonlocal write_calls
        write_calls += 1
        if write_calls == 2:
            raise OSError("injected index publication failure")
        if write_calls == 3:
            raise OSError("injected HTML rollback failure")
        original_atomic_write(path, content)

    monkeypatch.setattr(
        workspace, "_atomic_write_text", fail_index_then_html_rollback
    )
    new_root = workspace_root / "run-indeterminate"
    with pytest.raises(
        workspace.WorkspacePublicationError,
        match="injected index publication failure",
    ) as captured:
        mod.build_review_root(
            screenshot_dir=steps,
            manifest_path=manifest,
            contact_sheet=None,
            quick4_sheet=None,
            video=video,
            out_root=new_root,
            flow_id="indeterminate-flow",
            status="fail",
            last_run_at="2026-08-13T00:01:00+00:00",
        )

    error = captured.value
    assert error.committed is False
    assert error.cleanup_safe is False
    assert error.indeterminate is True
    assert error.original_error is error.__cause__
    assert error.rollback_error is not None
    assert "injected HTML rollback failure" in str(error.rollback_error)
    assert error.__cause__ is not None
    assert "injected index publication failure" in str(error.__cause__)
    # The old index remains the machine-readable truth, while the failed HTML
    # rollback leaves publication indeterminate. The run must survive because
    # deleting it would make that HTML point at a missing artifact root.
    assert (workspace_root / "index.json").read_bytes() == old_index
    assert (workspace_root / "UIreview.html").read_bytes() != old_html
    assert new_root.is_dir()

    monkeypatch.setattr(workspace, "_atomic_write_text", original_atomic_write)
    retry_run = {
        "runId": new_root.name,
        "flowId": "indeterminate-flow",
        "variantId": "default",
        "status": "fail",
        "lastRunAt": "2026-08-13T00:01:00+00:00",
        "testFile": None,
        "device": None,
        "stepCount": 1,
        "artifacts": {"reviewHtml": f"{new_root.name}/UIreview.html"},
    }
    workspace.write_workspace_index(
        workspace_root,
        retry_run,
        test_root=tmp_path / "missing-tests",
        project_root=tmp_path,
    )
    retried = json.loads((workspace_root / "index.json").read_text(encoding="utf-8"))
    assert [run["runId"] for run in retried["runs"]] == [
        "run-indeterminate",
        "run-existing",
    ]


def test_load_manifest_rejects_symlink_that_escapes_screenshot_root(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    outside = tmp_path / "outside.png"
    _png(outside)
    (steps / "escaped.png").symlink_to(outside)
    manifest = _manifest(steps)

    with pytest.raises(ValueError, match="outside screenshot root"):
        mod.load_manifest(manifest, screenshot_dir=steps)


def test_load_manifest_rejects_multiple_assets_for_one_file(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    (steps / "02-launch.png").symlink_to(steps / "01-launch.png")
    manifest = _manifest(steps)

    with pytest.raises(ValueError, match="same artifact file"):
        mod.load_manifest(manifest, screenshot_dir=steps)


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

    assert "Debug Cockpit" in html
    assert "failed first" in html
    assert 'data-filter="failed"' in html
    assert "Latest run needs attention" in html
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
    assert "Debug Cockpit" in html
    assert "Never-run flows" in html
    assert "Flow Inventory" in html
    assert 'class="tabs"' in html
    assert 'data-filter="pending"' in html
    assert 'class="table-wrap"' in html
    assert 'id="search"' in html
    assert 'class="flow-row"' in html
    assert 'class="card status-pending"' in html
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


def test_review_root_rejects_zero_step_runs(tmp_path):
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

    with pytest.raises(ValueError, match="at least one step item"):
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


def test_run_html_prioritizes_video_sheets_and_image_modal(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    manifest = _manifest(steps)
    video = tmp_path / "20260614-050607-ui.mp4"
    video.write_bytes(b"video")
    log = tmp_path / "test.log"
    log.write_text("log\n", encoding="utf-8")
    contact_sheet = tmp_path / "contact_sheet.png"
    quick4_sheet = tmp_path / "quick4_contact_sheet.png"
    _png(contact_sheet)
    _png(quick4_sheet)
    out_root = tmp_path / "build" / "snapshots" / "uitest-runs" / "20260614-050607-ui"

    mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        contact_sheet=contact_sheet,
        quick4_sheet=quick4_sheet,
        video=video,
        out_root=out_root,
        log=log,
        flow_id="auth_flow",
        variant_id="free_preview",
        status="fail",
        test_file="AuthFlowUITests.swift",
        device="STUB-UDID",
        last_run_at="2026-06-14T05:06:07+00:00",
    )

    html = (out_root / "UIreview.html").read_text(encoding="utf-8")
    assert "Run Evidence" in html
    assert "quick4_contact_sheet.png" in html
    assert "contact_sheet.png" in html
    assert 'data-modal-src="01-launch.png"' in html
    assert 'id="image-modal"' in html
    assert "document.addEventListener('keydown'" in html
    assert "KG UITest Run Review" in html


def test_review_html_escapes_untrusted_labels():
    mod = _load()
    index = {
        "schema": "kg.ios.uitest-review-workspace.v1",
        "summary": {"totalRuns": 1, "okRuns": 0, "failRuns": 1, "flows": 1, "variants": 1},
        "runs": [
            {
                "runId": "run-a",
                "flowId": '<script>alert("flow")</script>',
                "variantId": 'guest"><img src=x onerror=alert(1)>',
                "status": "fail",
                "lastRunAt": "2026-06-14T03:04:05+00:00",
                "testFile": 'SettingsFlowUITests.swift"><script>',
                "device": "SIM-1",
                "stepCount": 1,
                "artifacts": {"reviewHtml": "run-a/UIreview.html"},
            }
        ],
        "flows": [
            {
                "flowId": '<script>alert("flow")</script>',
                "runs": 1,
                "latestStatus": "fail",
                "lastRunAt": "2026-06-14T03:04:05+00:00",
                "variants": ['guest"><img src=x onerror=alert(1)>'],
            }
        ],
    }

    html = mod.render_workspace_html(index)

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html
    assert "<img" not in html
