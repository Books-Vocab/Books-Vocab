#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from catalog_review_manifest import build_manifest, collect_items
from catalog_review_profile import load_profile
from catalog_review_renderer import render_html
from catalog_review_state import build_review_state, load_review_state

DEFAULT_PROFILE_PATH = Path(__file__).with_name("catalog_review_profile.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a static catalog review desk for snapshot artifacts.")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    output_root = (args.output_root or source_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "review_state.json"

    profile = load_profile(args.profile.resolve())
    items = collect_items(source_root, profile)
    existing_state = load_review_state(state_path)
    review_state = build_review_state(items, profile, existing_state)
    state_path.write_text(json.dumps(review_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = build_manifest(items, profile, state_file=state_path.name, review_state=review_state)
    (output_root / "review_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_root / "review.html").write_text(render_html(manifest), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "sourceRoot": str(source_root),
                "outputRoot": str(output_root),
                "totalImages": len(items),
                "promiseCounts": manifest["promiseCounts"],
                "stateFile": str(state_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
