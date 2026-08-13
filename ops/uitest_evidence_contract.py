#!/usr/bin/env -S uv run --python 3.13 python
"""Fail-closed validation for one Simulator UITest visual evidence bundle.

The runner's exit code and a set of artifact paths are not enough to establish
visual evidence. This contract checks that the manifest has real, hashed step
PNGs, that the overview artifacts are non-empty, and that the bundle carries
the same source/UI World/device provenance as the test verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import struct
from pathlib import Path
from typing import Any

from uitest_review_page import load_manifest


def png_metadata(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise ValueError(f"PNG has invalid dimensions {width}x{height}: {path}")
    return {
        "width": width,
        "height": height,
        "byteSize": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _require_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} is missing or empty: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_fingerprint(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _before_bundle_artifact_open(_label: str, _path: Path) -> None:
    """Deterministic fault-injection seam after containment, before fd open."""


def _update_digest_with_file(
    digest: Any,
    label: str,
    path: Path,
    *,
    root: Path,
    root_label: str,
) -> None:
    resolved_root = root.resolve(strict=True)
    try:
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise ValueError(
            f"canonical {label} resolves outside {root_label}: {path}"
        ) from error
    probe = os.stat(path, follow_symlinks=False)
    if stat.S_ISLNK(probe.st_mode):
        raise ValueError(f"canonical {label} must not be a symlink: {path}")
    if not stat.S_ISREG(probe.st_mode) or probe.st_size <= 0:
        raise ValueError(f"{label} is missing or empty: {path}")

    _before_bundle_artifact_open(label, path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(
            f"canonical {label} changed or became a symlink before open: {path}"
        ) from error

    label_bytes = label.encode("utf-8")
    digest.update(len(label_bytes).to_bytes(4, "big"))
    digest.update(label_bytes)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if _stat_fingerprint(probe) != _stat_fingerprint(before):
            raise ValueError(f"bundle artifact path changed before hashing: {path}")
        digest.update(before.st_size.to_bytes(16, "big"))
        observed = 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            observed += len(chunk)
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if observed != before.st_size or _stat_fingerprint(before) != _stat_fingerprint(
        after
    ):
        raise ValueError(f"bundle artifact changed while hashing: {path}")
    try:
        current = os.stat(path, follow_symlinks=False)
        current_resolved = path.resolve(strict=True)
        current_resolved.relative_to(resolved_root)
    except OSError as error:
        raise ValueError(f"bundle artifact changed while hashing: {path}") from error
    except ValueError as error:
        raise ValueError(
            f"canonical {label} resolves outside {root_label}: {path}"
        ) from error
    if stat.S_ISLNK(current.st_mode) or _stat_fingerprint(
        after
    ) != _stat_fingerprint(current):
        raise ValueError(f"bundle artifact changed while hashing: {path}")


def canonical_bundle_sha256(
    *,
    manifest: Path,
    step_artifacts: list[tuple[str, Path]],
    contact_sheet: Path,
    quick4_sheet: Path,
    video: Path,
    review_html: Path,
    screenshot_root: Path,
    run_root: Path,
) -> str:
    """Hash every human-viewed artifact with stable role framing.

    review_state.json is intentionally absent: appending an attestation must
    not make that attestation invalidate itself. Published bundle artifacts
    are immutable for this call; descriptor fingerprints reject mutation or
    path replacement observed while any one artifact is hashed.
    """
    digest = hashlib.sha256(b"kg.ios.ui-evidence-bundle.v1\0")
    artifacts = [
        ("manifest", manifest, screenshot_root, "screenshot root"),
        *[
            (f"step:{rel_path}", path, screenshot_root, "screenshot root")
            for rel_path, path in step_artifacts
        ],
        ("contact-sheet:full", contact_sheet, run_root, "run root"),
        ("contact-sheet:quick4", quick4_sheet, run_root, "run root"),
        ("video", video, run_root, "run root"),
        ("review-html", review_html, run_root, "run root"),
    ]
    labels = [label for label, _path, _root, _root_label in artifacts]
    if len(labels) != len(set(labels)):
        raise ValueError("canonical bundle artifact labels must be unique")
    for label, path, root, root_label in artifacts:
        _update_digest_with_file(
            digest, label, path, root=root, root_label=root_label
        )
    return digest.hexdigest()


def bundle_sha256_for_run_root(
    run_root: Path,
    manifest_data: dict[str, Any],
) -> str:
    video_root = run_root / "uitest-videos"
    videos = sorted(path for path in video_root.iterdir() if path.is_file()) if video_root.is_dir() else []
    if len(videos) != 1:
        raise ValueError(
            f"canonical UITest bundle requires exactly one video, found {len(videos)}"
        )
    steps = [
        (str(item["relPath"]), run_root / str(item["relPath"]))
        for item in manifest_data["items"]
    ]
    return canonical_bundle_sha256(
        manifest=run_root / "review_manifest.json",
        step_artifacts=steps,
        contact_sheet=run_root / "contact_sheet.png",
        quick4_sheet=run_root / "quick4_contact_sheet.png",
        video=videos[0],
        review_html=run_root / "UIreview.html",
        screenshot_root=run_root,
        run_root=run_root,
    )


def validate_bundle(
    *,
    screenshot_dir: Path,
    manifest: Path,
    contact_sheet: Path,
    quick4_sheet: Path,
    video: Path,
    review_html: Path,
    source_commit: str,
    dataset_id: str,
    dataset_sha256: str,
    device: str,
    video_identity: dict[str, str],
    expected_video_run_id: str,
    selector: str | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    loaded = load_manifest(manifest, screenshot_dir=screenshot_dir)
    if loaded.get("source") != "uitest":
        raise ValueError("visual evidence manifest source must be 'uitest'")

    provenance = loaded.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("visual evidence manifest must contain provenance")
    expected = {
        "sourceCommit": source_commit,
        "datasetID": dataset_id,
        "datasetSHA256": dataset_sha256,
        "device": device,
    }
    if selector is not None:
        expected["selector"] = selector
    if variant is not None:
        expected["variant"] = variant
    for key, value in expected.items():
        if not value or provenance.get(key) != value:
            raise ValueError(
                f"visual evidence provenance mismatch for {key}: "
                f"expected {value!r}, actual {provenance.get(key)!r}"
            )

    contact_metadata = png_metadata(contact_sheet)
    quick4_metadata = png_metadata(quick4_sheet)
    _require_file(video, "UITest video")
    if not isinstance(video_identity, dict):
        raise ValueError("video identity must be an object")
    video_run_id = video_identity.get("runID")
    video_file = video_identity.get("file")
    video_sha256 = video_identity.get("sha256")
    actual_video_sha256 = _sha256_file(video)
    if not isinstance(video_run_id, str) or not video_run_id:
        raise ValueError("video identity runID must be nonempty")
    if not expected_video_run_id or video_run_id != expected_video_run_id:
        raise ValueError(
            "video identity runID mismatch: "
            f"expected {expected_video_run_id!r}, actual {video_run_id!r}"
        )
    if video_file != video.name:
        raise ValueError(
            f"video identity file mismatch: expected {video.name!r}, actual {video_file!r}"
        )
    if video_sha256 != actual_video_sha256:
        raise ValueError(
            "video identity sha256 mismatch: "
            f"expected {actual_video_sha256!r}, actual {video_sha256!r}"
        )
    _require_file(review_html, "UIreview HTML")
    html_bytes = review_html.read_bytes()
    html = html_bytes.decode("utf-8", errors="replace")
    if "KG UITest Run Review" not in html:
        raise ValueError("UIreview HTML does not contain the expected review root")

    items = loaded["items"]
    bundle_sha256 = canonical_bundle_sha256(
        manifest=manifest,
        step_artifacts=[
            (str(item["relPath"]), screenshot_dir / str(item["relPath"]))
            for item in items
        ],
        contact_sheet=contact_sheet,
        quick4_sheet=quick4_sheet,
        video=video,
        review_html=review_html,
        screenshot_root=screenshot_dir,
        run_root=review_html.parent,
    )
    return {
        "schema": "kg.ios.ui-evidence-contract.v1",
        "valid": True,
        "stepCount": len(items),
        "stepSha256": [item["sha256"] for item in items],
        "contactSheet": contact_metadata,
        "quick4Sheet": quick4_metadata,
        "videoByteSize": video.stat().st_size,
        "videoSha256": actual_video_sha256,
        "videoIdentity": video_identity,
        "reviewHtmlSha256": hashlib.sha256(html_bytes).hexdigest(),
        "bundleSHA256": bundle_sha256,
        "provenance": provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("validate", choices=["validate"])
    parser.add_argument("--screenshot-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--contact-sheet", required=True, type=Path)
    parser.add_argument("--quick4-sheet", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--review-html", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--video-run-id", required=True)
    parser.add_argument("--review-run-id", required=True)
    parser.add_argument("--video-file", required=True)
    parser.add_argument("--video-sha256", required=True)
    parser.add_argument("--selector")
    parser.add_argument("--variant")
    args = parser.parse_args()
    try:
        result = validate_bundle(
            screenshot_dir=args.screenshot_dir,
            manifest=args.manifest,
            contact_sheet=args.contact_sheet,
            quick4_sheet=args.quick4_sheet,
            video=args.video,
            review_html=args.review_html,
            source_commit=args.source_commit,
            dataset_id=args.dataset_id,
            dataset_sha256=args.dataset_sha256,
            device=args.device,
            video_identity={
                "runID": args.video_run_id,
                "file": args.video_file,
                "sha256": args.video_sha256,
            },
            expected_video_run_id=args.review_run_id,
            selector=args.selector,
            variant=args.variant,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "kg.ios.ui-evidence-contract.v1", "valid": False, "error": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
