from __future__ import annotations

import json
from pathlib import Path


def load_review_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_review_state(items: list[dict], profile: dict, existing_state: dict | None = None) -> dict:
    existing_entries = (existing_state or {}).get("entries", {})
    entries: dict[str, dict] = {}
    for item in items:
        previous = existing_entries.get(item["assetID"], {})
        entries[item["assetID"]] = {
            "status": previous.get("status", ""),
            "note": previous.get("note", ""),
            "promise": item["promise"],
            "category": item["category"],
            "title": item["title"],
            "device": item["device"],
            "appearance": item["appearance"],
            "relPath": item["relPath"],
        }
    return {
        "schema": "kg.catalog.review.state.v1",
        "profile": {
            "path": str(profile.get("_path", "")),
            "schema": profile.get("schema"),
        },
        "entries": entries,
    }
