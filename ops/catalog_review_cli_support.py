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


def review_html_path(root: Path) -> Path:
    return root / "review.html"


def build_artifact_refs(root: Path) -> dict[str, str]:
    manifest_path, state_path = resolve_paths(root)
    html_path = review_html_path(root)
    return {
        "manifest": str(manifest_path),
        "state": str(state_path),
        "html": str(html_path),
    }


def build_permalink(root: Path, asset_id: str) -> str:
    return f"file://{review_html_path(root)}#asset-{asset_id}"


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


def load_review_context(root: Path) -> tuple[dict, dict]:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    return hydrate_manifest(manifest, state), state


def load_review_artifacts(root: Path, *, hydrate: bool, include_html: bool) -> dict:
    manifest_path, state_path = resolve_paths(root)
    payload = {
        "manifest_path": manifest_path,
        "state_path": state_path,
        "manifest": load_json(manifest_path),
        "state": load_json(state_path),
    }
    if hydrate:
        payload["manifest"] = hydrate_manifest(payload["manifest"], payload["state"])
    if include_html:
        html_path = review_html_path(root)
        payload["html_path"] = html_path
        payload["html_text"] = html_path.read_text(encoding="utf-8")
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
