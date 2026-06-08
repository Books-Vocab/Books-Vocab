from __future__ import annotations

from catalog_review_cli_serialization import effective_status


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
            "hero" if item.get("heroCandidate") else "",
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
