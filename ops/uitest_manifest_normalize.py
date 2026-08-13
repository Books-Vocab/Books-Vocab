#!/usr/bin/env -S uv run --python 3.13 python
"""Rebind legacy UITest visual manifests to copied PNG bytes.

Some older source worktrees emit a review manifest with dimensions only.  The
stable evidence helper may copy that historical output, but the machine
contract requires byte size, SHA-256, and current run provenance.  This small
stdlib-only adapter repairs the copied manifest without rerunning or changing
the source UITest.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from png_integrity import png_metadata


def normalize_manifest(
    *,
    manifest_path: Path,
    screenshot_dir: Path,
    source_commit: str,
    dataset_id: str,
    dataset_sha256: str,
    device: str,
    selector: str,
    variant: str | None = None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("source") != "uitest":
        raise ValueError("visual evidence manifest source must be 'uitest'")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("visual evidence manifest must contain at least one item")

    screenshot_root = screenshot_dir.resolve()
    seen_paths: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"manifest item {index} is not an object")
        rel_path = item.get("relPath")
        if (
            not isinstance(rel_path, str)
            or not rel_path
            or Path(rel_path).is_absolute()
            or ".." in Path(rel_path).parts
        ):
            raise ValueError(f"manifest item {index} has unsafe relPath: {rel_path!r}")
        if rel_path in seen_paths:
            raise ValueError(f"manifest contains duplicate relPath: {rel_path}")
        seen_paths.add(rel_path)
        artifact = (screenshot_dir / rel_path).resolve()
        try:
            artifact.relative_to(screenshot_root)
        except ValueError as error:
            raise ValueError(f"manifest item escapes screenshot root: {rel_path!r}") from error
        if not artifact.is_file():
            raise ValueError(f"manifest references missing step PNG: {artifact}")
        item.update(png_metadata(artifact))

    expected_provenance = {
        "sourceCommit": source_commit,
        "datasetID": dataset_id,
        "datasetSHA256": dataset_sha256,
        "device": device,
        "selector": selector,
    }
    if variant:
        expected_provenance["variant"] = variant
    existing_provenance = manifest.get("provenance")
    if existing_provenance is not None:
        if not isinstance(existing_provenance, dict):
            raise ValueError("legacy visual evidence provenance must be an object")
        for key, value in expected_provenance.items():
            if key not in existing_provenance:
                raise ValueError(f"legacy visual evidence provenance missing {key}")
            if existing_provenance[key] != value:
                raise ValueError(
                    f"visual evidence provenance mismatch for {key}: "
                    f"expected {value!r}, actual {existing_provenance[key]!r}"
                )
        if "variant" in existing_provenance and not variant:
            raise ValueError(
                "visual evidence provenance contains variant but current run did not provide one"
            )
        provenance = dict(existing_provenance)
    else:
        provenance = expected_provenance
    manifest["provenance"] = provenance
    temporary = manifest_path.with_name(f".{manifest_path.name}.normalize-tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--screenshot-dir", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--selector", required=True)
    parser.add_argument("--variant")
    args = parser.parse_args()
    normalize_manifest(
        manifest_path=args.manifest,
        screenshot_dir=args.screenshot_dir,
        source_commit=args.source_commit,
        dataset_id=args.dataset_id,
        dataset_sha256=args.dataset_sha256,
        device=args.device,
        selector=args.selector,
        variant=args.variant,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
