from __future__ import annotations

import json
from pathlib import Path

from catalog_canvas_renderer import render_canvas_html
from catalog_review_renderer import render_html


def hydrate_manifest(manifest: dict, review_state: dict) -> dict:
    state_entries = review_state.get("entries", {})
    items = []
    state_counts: dict[str, int] = {}
    for item in manifest["items"]:
        state_entry = state_entries.get(item["assetID"], {})
        hydrated = dict(item)
        hydrated["reviewStatus"] = state_entry.get("status", "")
        hydrated["reviewNote"] = state_entry.get("note", "")
        items.append(hydrated)
        if hydrated["reviewStatus"]:
            state_counts[hydrated["reviewStatus"]] = state_counts.get(hydrated["reviewStatus"], 0) + 1

    next_manifest = dict(manifest)
    next_manifest["items"] = items
    next_manifest["stateCounts"] = state_counts
    return next_manifest


def write_review_outputs(root: Path, manifest: dict, review_state: dict) -> None:
    hydrated = hydrate_manifest(manifest, review_state)
    (root / "review_manifest.json").write_text(
        json.dumps(hydrated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "review.html").write_text(render_html(hydrated), encoding="utf-8")
    (root / "catalog.html").write_text(render_canvas_html(hydrated), encoding="utf-8")
