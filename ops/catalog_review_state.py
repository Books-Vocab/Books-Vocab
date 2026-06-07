from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, UTC


def load_review_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def review_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
            "updatedAt": previous.get("updatedAt"),
            "history": previous.get("history", []),
        }
    return {
        "schema": "kg.catalog.review.state.v1",
        "profile": {
            "path": str(profile.get("_path", "")),
            "schema": profile.get("schema"),
        },
        "entries": entries,
    }


def append_history(entry: dict, *, action: str, status: str, note: str) -> None:
    history = list(entry.get("history", []))
    history.append({
        "at": review_timestamp(),
        "action": action,
        "status": status,
        "note": note,
    })
    entry["history"] = history
    entry["updatedAt"] = history[-1]["at"]
