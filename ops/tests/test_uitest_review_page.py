from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path
import zlib


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"


def _load():
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    spec = importlib.util.spec_from_file_location(
        "uitest_review_page", OPS / "uitest_review_page.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(path: Path) -> None:
    width, height = 12, 12

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
    step = root / "01-state.png"
    data = step.read_bytes()
    manifest = {
        "schema": "kg.visual-review.sheet.v1",
        "source": "uitest",
        "items": [
            {
                "assetID": "01-state",
                "relPath": step.name,
                "surface": "AuthFlowUITests",
                "stateLabel": "loaded",
                "appearance": "light",
                "width": struct.unpack(">I", data[16:20])[0],
                "height": struct.unpack(">I", data[20:24])[0],
                "byteSize": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
    }
    path = root / "review_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_build_review_root_is_one_run_without_parent_index(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-state.png")
    manifest = _manifest(steps)
    log = tmp_path / "test.log"
    log.write_text("KG_PERF state.loaded\n", encoding="utf-8")
    video = tmp_path / "run.mp4"
    video.write_bytes(b"video")
    out_root = tmp_path / "run-bundle"

    payload = mod.build_review_root(
        screenshot_dir=steps,
        manifest_path=manifest,
        video=video,
        out_root=out_root,
        log=log,
        flow_id="auth_flow",
        variant_id="signed-in",
        status="ok",
        test_file="AuthFlowUITests.swift",
        device="STUB-UDID",
        last_run_at="2026-08-16T00:00:00+00:00",
    )

    assert payload["html"] == str(out_root / "UIreview.html")
    assert set(payload) == {"schema", "root", "html", "manifest", "state", "videos"}
    assert (out_root / "UIreview.html").is_file()
    assert (out_root / "review_manifest.json").is_file()
    assert (out_root / "review_state.json").is_file()
    assert (out_root / "uitest-videos" / "run.mp4").read_bytes() == b"video"
    assert (out_root / "test.log").read_text(encoding="utf-8") == "KG_PERF state.loaded\n"
    assert not (tmp_path / "index.json").exists()
    assert not (tmp_path / "UIreview.html").exists()
    html = (out_root / "UIreview.html").read_text(encoding="utf-8")
    assert "href=\"../UIreview.html\"" not in html
    assert "01-state.png" in html


def test_build_review_root_refuses_overwrite(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-state.png")
    manifest = _manifest(steps)
    out_root = tmp_path / "run-bundle"
    out_root.mkdir()
    (out_root / "sentinel").write_text("keep", encoding="utf-8")

    try:
        mod.build_review_root(
            screenshot_dir=steps,
            manifest_path=manifest,
            out_root=out_root,
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("non-empty run bundle must not be overwritten")
    assert (out_root / "sentinel").read_text(encoding="utf-8") == "keep"
