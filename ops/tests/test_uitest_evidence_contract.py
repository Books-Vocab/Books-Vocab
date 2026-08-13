from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load():
    if str(ROOT / "ops") not in sys.path:
        sys.path.insert(0, str(ROOT / "ops"))
    spec = importlib.util.spec_from_file_location(
        "uitest_evidence_contract", ROOT / "ops" / "uitest_evidence_contract.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _png(path: Path, width: int = 100, height: int = 200):
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        + width.to_bytes(4, "big") + height.to_bytes(4, "big")
    )


def _bundle(tmp_path: Path):
    mod = _load()
    steps = tmp_path / "steps"
    steps.mkdir()
    _png(steps / "01-launch.png")
    data = (steps / "01-launch.png").read_bytes()
    manifest = steps / "review_manifest.json"
    manifest.write_text(json.dumps({
        "schema": "kg.visual-review.sheet.v1",
        "source": "uitest",
        "provenance": {
            "sourceCommit": "abc123",
            "datasetID": "marketing_demo",
            "datasetSHA256": "dataset-sha",
            "device": "SIM-1",
            "selector": "VocabularyLibraryFlowUITests",
            "variant": "dataset:marketing_demo",
        },
        "items": [{
            "assetID": "01-launch",
            "relPath": "01-launch.png",
            "stateLabel": "launch",
            "width": 100,
            "height": 200,
            "byteSize": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }],
    }), encoding="utf-8")
    contact = tmp_path / "contact_sheet.png"
    quick4 = tmp_path / "quick4_contact_sheet.png"
    _png(contact, 300, 200)
    _png(quick4, 400, 200)
    video = tmp_path / "flow.mp4"
    video.write_bytes(b"mp4")
    html = tmp_path / "UIreview.html"
    html.write_text("<title>KG UITest Run Review</title>", encoding="utf-8")
    kwargs = dict(
        screenshot_dir=steps,
        manifest=manifest,
        contact_sheet=contact,
        quick4_sheet=quick4,
        video=video,
        review_html=html,
        source_commit="abc123",
        dataset_id="marketing_demo",
        dataset_sha256="dataset-sha",
        device="SIM-1",
        video_identity={
            "runID": "test-run-123",
            "file": video.name,
            "sha256": hashlib.sha256(b"mp4").hexdigest(),
        },
        expected_video_run_id="test-run-123",
        selector="VocabularyLibraryFlowUITests",
        variant="dataset:marketing_demo",
    )
    return mod, kwargs


def test_validate_bundle_requires_real_hashed_steps_and_provenance(tmp_path):
    mod, kwargs = _bundle(tmp_path)
    result = mod.validate_bundle(**kwargs)
    assert result["valid"] is True
    assert result["stepCount"] == 1
    assert result["videoByteSize"] == 3
    assert result["videoSha256"] == hashlib.sha256(b"mp4").hexdigest()
    assert result["reviewHtmlSha256"] == hashlib.sha256(
        b"<title>KG UITest Run Review</title>"
    ).hexdigest()
    assert len(result["bundleSHA256"]) == 64


def test_validate_bundle_rejects_tampered_step(tmp_path):
    mod, kwargs = _bundle(tmp_path)
    step = tmp_path / "steps" / "01-launch.png"
    step.write_bytes(step.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="mismatch"):
        mod.validate_bundle(**kwargs)


def test_validate_bundle_rejects_missing_provenance(tmp_path):
    mod, kwargs = _bundle(tmp_path)
    data = json.loads(kwargs["manifest"].read_text(encoding="utf-8"))
    del data["provenance"]
    kwargs["manifest"].write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="must contain provenance"):
        mod.validate_bundle(**kwargs)


def test_validate_bundle_records_video_hash_after_same_size_change(tmp_path):
    mod, kwargs = _bundle(tmp_path)
    kwargs["video"].write_bytes(b"xyz")
    kwargs["video_identity"]["sha256"] = hashlib.sha256(b"xyz").hexdigest()
    result = mod.validate_bundle(**kwargs)
    assert result["videoSha256"] == hashlib.sha256(b"xyz").hexdigest()


def test_validate_bundle_rejects_video_from_a_different_run(tmp_path):
    mod, kwargs = _bundle(tmp_path)
    kwargs["video_identity"] = {
        "runID": "other-run",
        "file": "flow.mp4",
        "sha256": hashlib.sha256(b"mp4").hexdigest(),
    }
    with pytest.raises(ValueError, match="video identity"):
        mod.validate_bundle(**kwargs)


def test_validate_bundle_rejects_html_without_review_root(tmp_path):
    mod, kwargs = _bundle(tmp_path)
    kwargs["review_html"].write_text("<title>still same length</title>", encoding="utf-8")
    with pytest.raises(ValueError, match="expected review root"):
        mod.validate_bundle(**kwargs)


def test_validate_bundle_rechecks_step_containment_at_canonical_open(
    tmp_path, monkeypatch
):
    mod, kwargs = _bundle(tmp_path)
    step = kwargs["screenshot_dir"] / "01-launch.png"
    outside = tmp_path / "outside-step.png"
    outside.write_bytes(step.read_bytes())
    swapped = False

    def replace_after_containment(label, path):
        nonlocal swapped
        if label != "step:01-launch.png":
            return
        assert path == step
        step.unlink()
        step.symlink_to(outside)
        swapped = True

    # This seam belongs inside the canonical contained-open path, after its
    # resolve/containment probe and immediately before fd open.
    monkeypatch.setattr(
        mod,
        "_before_bundle_artifact_open",
        replace_after_containment,
        raising=False,
    )

    with pytest.raises(ValueError, match="symlink|outside screenshot root"):
        mod.validate_bundle(**kwargs)
    assert swapped is True
