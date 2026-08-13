from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load():
    import sys

    if str(ROOT / "ops") not in sys.path:
        sys.path.insert(0, str(ROOT / "ops"))
    spec = importlib.util.spec_from_file_location(
        "uitest_review_attest", ROOT / "ops" / "uitest_review_attest.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_root(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    step = run / "01-launch.png"
    step.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        + (100).to_bytes(4, "big") + (200).to_bytes(4, "big")
    )
    import hashlib

    data = step.read_bytes()
    (run / "review_manifest.json").write_text(json.dumps({
        "schema": "kg.visual-review.sheet.v1",
        "source": "uitest",
        "provenance": {
            "sourceCommit": "abc",
            "datasetID": "demo",
            "datasetSHA256": "sha",
            "device": "SIM",
        },
        "items": [{
            "assetID": "01-launch",
            "relPath": "01-launch.png",
            "width": 100,
            "height": 200,
            "byteSize": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }],
    }), encoding="utf-8")
    for name, width in (("contact_sheet.png", 300), ("quick4_contact_sheet.png", 400)):
        (run / name).write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
            + width.to_bytes(4, "big") + (200).to_bytes(4, "big")
        )
    video_root = run / "uitest-videos"
    video_root.mkdir()
    (video_root / "flow.mp4").write_bytes(b"video-evidence")
    (run / "UIreview.html").write_text(
        "<title>KG UITest Run Review</title><p>bundle A</p>",
        encoding="utf-8",
    )
    return run


def test_attest_pass_requires_and_records_all_steps(tmp_path):
    mod = _load()
    run = _run_root(tmp_path)
    entry = mod.attest(
        run,
        reviewer="codex",
        status="pass",
        notes="checked full contact sheet and step order",
        all_steps=True,
        visual_checks=["full contact sheet", "step order"],
    )
    state = json.loads((run / "review_state.json").read_text(encoding="utf-8"))
    assert state["schema"] == "kg.ui.review-state.v2"
    assert state["entries"][0]["assetIDs"] == ["01-launch"]
    assert len(entry["evidenceRootSHA256"]) == 64
    assert len(entry["bundleSHA256"]) == 64
    assert mod.attestation_matches_current_bundle(run, entry) is True


def test_attest_pass_rejects_partial_asset_review(tmp_path):
    mod = _load()
    run = _run_root(tmp_path)
    with pytest.raises(ValueError, match="must name reviewed assets"):
        mod.attest(
            run,
            reviewer="codex",
            status="pass",
            notes="partial",
            asset_ids=[],
        )


def test_attest_rejects_duplicate_asset_ids(tmp_path):
    mod = _load()
    run = _run_root(tmp_path)
    first = run / "01-launch.png"
    second = run / "02-launch.png"
    second.write_bytes(first.read_bytes())
    manifest_path = run / "review_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    duplicate = dict(manifest["items"][0])
    duplicate["relPath"] = second.name
    manifest["items"].append(duplicate)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate assetID|assetIDs must be unique"):
        mod.attest(
            run,
            reviewer="codex",
            status="pass",
            notes="duplicate asset regression",
            all_steps=True,
            visual_checks=["full contact sheet"],
        )


def test_attest_migrates_legacy_empty_review_state(tmp_path):
    mod = _load()
    run = _run_root(tmp_path)
    (run / "review_state.json").write_text(
        json.dumps({"schema": "kg.ui.review-state.v1", "entries": {}}),
        encoding="utf-8",
    )

    mod.attest(
        run,
        reviewer="codex",
        status="pass",
        notes="migrated legacy empty state",
        all_steps=True,
        visual_checks=["full contact sheet", "step order"],
    )

    state = json.loads((run / "review_state.json").read_text(encoding="utf-8"))
    assert state["schema"] == "kg.ui.review-state.v2"
    assert len(state["entries"]) == 1


def test_attest_concurrent_writers_preserve_all_entries(tmp_path):
    run = _run_root(tmp_path)
    script = ROOT / "ops" / "uitest_review_attest.py"
    writer_count = 16
    launch_barrier = (
        "import os, sys; "
        "sys.stdin.buffer.read(1); "
        "os.execv(sys.executable, [sys.executable, sys.argv[1], *sys.argv[2:]])"
    )
    processes = []
    for index in range(writer_count):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                launch_barrier,
                str(script),
                str(run),
                "--reviewer",
                f"writer-{index}",
                "--status",
                "pass",
                "--notes",
                f"concurrent writer {index}",
                "--all-steps",
                "--visual-check",
                "step integrity",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        processes.append(process)

    for process in processes:
        assert process.stdin is not None
        process.stdin.write(b"x")
        process.stdin.close()
        process.stdin = None

    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            failures.append(
                (process.returncode, stdout.decode(), stderr.decode())
            )
    assert failures == []

    state = json.loads((run / "review_state.json").read_text(encoding="utf-8"))
    assert state["schema"] == "kg.ui.review-state.v2"
    assert len(state["entries"]) == writer_count
    assert {entry["reviewer"] for entry in state["entries"]} == {
        f"writer-{index}" for index in range(writer_count)
    }


def test_validator_and_attester_share_canonical_bundle_digest(tmp_path):
    mod = _load()
    run = _run_root(tmp_path)
    import uitest_evidence_contract as contract

    validated = contract.validate_bundle(
        screenshot_dir=run,
        manifest=run / "review_manifest.json",
        contact_sheet=run / "contact_sheet.png",
        quick4_sheet=run / "quick4_contact_sheet.png",
        video=run / "uitest-videos" / "flow.mp4",
        review_html=run / "UIreview.html",
        source_commit="abc",
        dataset_id="demo",
        dataset_sha256="sha",
        device="SIM",
    )
    entry = mod.attest(
        run,
        reviewer="codex",
        status="pass",
        notes="canonical digest parity",
        all_steps=True,
        visual_checks=["all bundle artifacts"],
    )

    assert entry["bundleSHA256"] == validated["bundleSHA256"]
    assert entry["evidenceRootSHA256"] == validated["bundleSHA256"]
    # review_state.json is intentionally outside the bundle to avoid a
    # digest that invalidates itself when the attestation is appended.
    assert mod.attestation_matches_current_bundle(run, entry) is True


@pytest.mark.parametrize(
    "artifact",
    [
        "review_manifest.json",
        "01-launch.png",
        "contact_sheet.png",
        "quick4_contact_sheet.png",
        "uitest-videos/flow.mp4",
        "UIreview.html",
    ],
)
def test_same_size_human_artifact_mutation_invalidates_attestation(
    tmp_path, artifact
):
    mod = _load()
    run = _run_root(tmp_path)
    entry = mod.attest(
        run,
        reviewer="codex",
        status="pass",
        notes="before same-size mutation",
        all_steps=True,
        visual_checks=["all bundle artifacts"],
    )
    target = run / artifact
    original = target.read_bytes()
    if artifact == "review_manifest.json":
        mutated = original.replace(b'"abc"', b'"abd"', 1)
    else:
        mutated = bytearray(original)
        mutated[-1] ^= 1
        mutated = bytes(mutated)
    assert len(mutated) == len(original)
    assert mutated != original
    target.write_bytes(mutated)

    assert mod.attestation_matches_current_bundle(run, entry) is False


@pytest.mark.parametrize(
    "artifact",
    [
        "contact_sheet.png",
        "quick4_contact_sheet.png",
        "uitest-videos/flow.mp4",
        "UIreview.html",
    ],
)
def test_canonical_bundle_rejects_external_human_artifact_symlink(
    tmp_path, artifact
):
    mod = _load()
    run = _run_root(tmp_path)
    target = run / artifact
    outside = tmp_path / f"outside-{target.name}"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(ValueError, match="outside run root"):
        mod.attest(
            run,
            reviewer="codex",
            status="pass",
            notes="external symlink must not enter the canonical bundle",
            all_steps=True,
            visual_checks=["all bundle artifacts"],
        )
