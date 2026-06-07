from __future__ import annotations

import json
from pathlib import Path

from catalog_review_sync import hydrate_manifest


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_paths(root: Path) -> tuple[Path, Path]:
    manifest_path = root / "review_manifest.json"
    state_path = root / "review_state.json"
    return manifest_path, state_path


def load_review_context(root: Path) -> tuple[dict, dict]:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    return hydrate_manifest(manifest, state), state


def effective_status(item: dict, state: dict) -> str:
    return state["entries"].get(item["assetID"], {}).get("status") or item.get("reviewStatus", "")


def matches_filters(
    item: dict,
    state: dict,
    *,
    promise: str | None,
    category: str | None,
    status: str | None,
    search: str | None,
) -> bool:
    current_state = state["entries"].get(item["assetID"], {})
    if promise and item["promise"] != promise:
        return False
    if category and item["category"] != category:
        return False
    if status is not None and effective_status(item, state) != status:
        return False
    if search:
        hay = " ".join([
            item["assetID"],
            item["category"],
            item["title"],
            item["device"],
            item["appearance"],
            item["relPath"],
            current_state.get("status", ""),
            current_state.get("note", ""),
        ]).lower()
        if search.lower() not in hay:
            return False
    return True


def filtered_items(
    manifest: dict,
    state: dict,
    *,
    promise: str | None,
    category: str | None,
    status: str | None,
    search: str | None,
) -> list[dict]:
    return [
        item
        for item in manifest["items"]
        if matches_filters(item, state, promise=promise, category=category, status=status, search=search)
    ]
