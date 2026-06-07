from __future__ import annotations

from pathlib import Path
from catalog_review_cli_artifacts import build_permalink


def build_filter_payload(
    *,
    promise: str | None,
    category: str | None,
    status: str | None,
    search: str | None,
    limit: int | None,
    status_key: str = "status",
) -> dict:
    payload = {
        "promise": promise,
        "category": category,
        "search": search,
        "limit": limit,
    }
    payload[status_key] = status
    return payload


def effective_status(item: dict, state: dict) -> str:
    return state["entries"].get(item["assetID"], {}).get("status") or item.get("reviewStatus", "")


def find_item_by_asset_id(manifest: dict, asset_id: str) -> dict | None:
    return next((entry for entry in manifest["items"] if entry["assetID"] == asset_id), None)


def serialize_review_item(
    root: Path,
    item: dict,
    state: dict,
    *,
    include_updated_at: bool = False,
) -> dict:
    payload = {
        **item,
        "effectiveStatus": effective_status(item, state),
        "permalink": build_permalink(root, item["assetID"]),
    }
    if include_updated_at:
        payload["updatedAt"] = state["entries"].get(item["assetID"], {}).get("updatedAt")
    return payload


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
