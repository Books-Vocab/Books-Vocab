from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load():
    ops = ROOT / "ops"
    if str(ops) not in sys.path:
        sys.path.insert(0, str(ops))
    spec = importlib.util.spec_from_file_location(
        "uitest_manifest_normalize", ops / "uitest_manifest_normalize.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _png(path: Path, payload: bytes = b"legacy-step") -> None:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"\x00\xff\x00\x00"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw + payload[:0]))
        + chunk(b"IEND", b"")
    )


def test_normalize_manifest_rebinds_png_metadata_and_provenance(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    step = steps / "01-launch.png"
    _png(step)
    manifest = steps / "review_manifest.json"
    manifest.write_text(json.dumps({
        "schema": "kg.visual-review.sheet.v1",
        "source": "uitest",
        "items": [{"assetID": "01-launch", "relPath": "01-launch.png", "width": 1}],
    }), encoding="utf-8")

    mod.normalize_manifest(
        manifest_path=manifest,
        screenshot_dir=steps,
        source_commit="abc123",
        dataset_id="marketing_demo",
        dataset_sha256="dataset-sha",
        device="SIM-1",
        selector="--method SettingsFlowUITests/testSettingsFlow",
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    item = payload["items"][0]
    data = step.read_bytes()
    assert item["byteSize"] == len(data)
    assert item["sha256"] == hashlib.sha256(data).hexdigest()
    assert item["width"] == 1
    assert item["height"] == 1
    assert payload["provenance"] == {
        "sourceCommit": "abc123",
        "datasetID": "marketing_demo",
        "datasetSHA256": "dataset-sha",
        "device": "SIM-1",
        "selector": "--method SettingsFlowUITests/testSettingsFlow",
    }


def test_normalize_manifest_rejects_path_escape(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    outside = tmp_path / "outside.png"
    _png(outside)
    manifest = steps / "review_manifest.json"
    manifest.write_text(json.dumps({
        "source": "uitest",
        "items": [{"assetID": "escape", "relPath": "../outside.png"}],
    }), encoding="utf-8")

    try:
        mod.normalize_manifest(
            manifest_path=manifest,
            screenshot_dir=steps,
            source_commit="abc123",
            dataset_id="marketing_demo",
            dataset_sha256="dataset-sha",
            device="SIM-1",
            selector="--file SettingsFlowUITests.swift",
        )
    except ValueError as error:
        assert "unsafe relPath" in str(error)
    else:
        raise AssertionError("path escape must be rejected")


def test_normalize_manifest_rejects_truncated_png(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    (steps / "01-launch.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    manifest = steps / "review_manifest.json"
    manifest.write_text(json.dumps({
        "source": "uitest",
        "items": [{"assetID": "01-launch", "relPath": "01-launch.png"}],
    }), encoding="utf-8")
    try:
        mod.normalize_manifest(
            manifest_path=manifest,
            screenshot_dir=steps,
            source_commit="abc123",
            dataset_id="marketing_demo",
            dataset_sha256="dataset-sha",
            device="SIM-1",
            selector="--file SettingsFlowUITests.swift",
        )
    except ValueError as error:
        assert "PNG" in str(error)
    else:
        raise AssertionError("truncated PNG must be rejected")


def test_normalize_manifest_rejects_stale_provenance(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    manifest = steps / "review_manifest.json"
    manifest.write_text(json.dumps({
        "source": "uitest",
        "provenance": {"sourceCommit": "stale"},
        "items": [{"assetID": "01-launch", "relPath": "01-launch.png"}],
    }), encoding="utf-8")
    try:
        mod.normalize_manifest(
            manifest_path=manifest,
            screenshot_dir=steps,
            source_commit="abc123",
            dataset_id="marketing_demo",
            dataset_sha256="dataset-sha",
            device="SIM-1",
            selector="--file SettingsFlowUITests.swift",
        )
    except ValueError as error:
        assert "provenance mismatch" in str(error)
    else:
        raise AssertionError("stale provenance must be rejected")


def test_normalize_manifest_rejects_partial_provenance(tmp_path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    manifest = steps / "review_manifest.json"
    manifest.write_text(json.dumps({
        "source": "uitest",
        "provenance": {"sourceCommit": "abc123"},
        "items": [{"assetID": "01-launch", "relPath": "01-launch.png"}],
    }), encoding="utf-8")
    try:
        mod.normalize_manifest(
            manifest_path=manifest,
            screenshot_dir=steps,
            source_commit="abc123",
            dataset_id="marketing_demo",
            dataset_sha256="dataset-sha",
            device="SIM-1",
            selector="--file SettingsFlowUITests.swift",
        )
    except ValueError as error:
        assert "missing datasetID" in str(error)
    else:
        raise AssertionError("partial provenance must be rejected")
