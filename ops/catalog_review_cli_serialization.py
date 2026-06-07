from __future__ import annotations

from pathlib import Path

from catalog_review_cli_artifacts import build_permalink


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
