#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from catalog_review_manifest import build_manifest, collect_items
from catalog_review_profile import load_profile
from catalog_review_sync import write_review_outputs

DEFAULT_PROFILE_PATH = Path(__file__).with_name("catalog_review_profile.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a static catalog UI atlas for snapshot artifacts.")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    output_root = (args.output_root or source_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    profile = load_profile(args.profile.resolve())
    items = collect_items(source_root, profile)
    manifest = build_manifest(items, profile)
    write_review_outputs(output_root, manifest)
    print(
        json.dumps(
            {
                "status": "ok",
                "sourceRoot": str(source_root),
                "outputRoot": str(output_root),
                "totalImages": len(items),
                "promiseCounts": manifest["promiseCounts"],
                "canvasHtml": str(output_root / "catalog.html"),
                "reviewManifest": str(output_root / "review_manifest.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
