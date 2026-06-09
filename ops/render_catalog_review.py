#!/usr/bin/env -S uv run --python 3.13 python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from catalog_review_manifest import build_manifest, collect_items
from catalog_review_profile import load_profile
from catalog_review_state import build_review_state, load_review_state
from catalog_review_sync import write_review_outputs

DEFAULT_PROFILE_PATH = Path(__file__).with_name("catalog_review_profile.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a static catalog review desk for snapshot artifacts.")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    return parser.parse_args()


def _require_source_declared(items: list[dict], source_root: Path) -> None:
    """Fail loud when a *blessed* source set has a surface missing from taxonomy.

    The gallery's premise is that every lane is *declared* by the iOS
    `CatalogScene` manifest (emitted as `catalog_index.json`), never guessed from
    pixels/regex. The enforcement is presence-gated:

    - No `catalog_index.json` → a legacy / un-blessed artifact rendered in
      explicit heuristic-fallback mode; nothing to enforce.
    - Index present → it is the source of truth and must be COMPLETE. A rendered
      category absent from it is drift (a surface added without declaring it):
      refuse to render and name the offenders, so the fix is to declare the
      surface in source, not to let a pixel/regex guess leak into the gallery.
    """
    if not (source_root / "catalog_index.json").is_file():
        return
    undeclared = sorted({item["category"] for item in items if not item.get("sourceDeclared")})
    if undeclared:
        listed = "\n  - ".join(undeclared)
        raise SystemExit(
            f"catalog gallery: {len(undeclared)} surface(s) missing from "
            f"catalog_index.json (source-of-truth taxonomy) under {source_root}:\n"
            f"  - {listed}\n"
            "Declare each in ios CatalogScene.swift (re-render snapshots) — the "
            "gallery does not guess lanes from pixels/regex."
        )


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    output_root = (args.output_root or source_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "review_state.json"

    profile = load_profile(args.profile.resolve())
    items = collect_items(source_root, profile)
    _require_source_declared(items, source_root)
    existing_state = load_review_state(state_path)
    review_state = build_review_state(items, profile, existing_state)
    state_path.write_text(json.dumps(review_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = build_manifest(
        items,
        profile,
        state_file=state_path.name,
        review_state=review_state,
        source_root=source_root,
    )
    write_review_outputs(output_root, manifest, review_state)
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
