from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from catalog_review_cli_support import effective_status, filtered_items, load_review_context, resolve_paths
from catalog_review_report import build_report_payload


def cmd_summary(root: Path) -> int:
    manifest_path, state_path = resolve_paths(root)
    manifest, state = load_review_context(root)
    payload = {
        "status": "ok",
        "manifest": str(manifest_path),
        "state": str(state_path),
        "totalImages": manifest["totalImages"],
        "stateEntries": len(state["entries"]),
        "promiseCounts": manifest["promiseCounts"],
        "stateCounts": manifest.get("stateCounts", {}),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_show(root: Path, asset_id: str) -> int:
    manifest, state = load_review_context(root)
    item = next((entry for entry in manifest["items"] if entry["assetID"] == asset_id), None)
    if item is None:
        print(json.dumps({"status": "error", "error": "asset-not-found", "assetID": asset_id}, ensure_ascii=False))
        return 1
    payload = {
        "status": "ok",
        "asset": item,
        "state": state["entries"].get(asset_id, {}),
        "history": state["entries"].get(asset_id, {}).get("history", []),
        "permalink": f"file://{root / 'review.html'}#asset-{asset_id}",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_list(
    root: Path,
    *,
    promise: str | None,
    category: str | None,
    status: str | None,
    search: str | None,
    limit: int | None,
) -> int:
    manifest, state = load_review_context(root)
    matches = [
        {
            **item,
            "effectiveStatus": effective_status(item, state),
            "permalink": f"file://{root / 'review.html'}#asset-{item['assetID']}",
        }
        for item in filtered_items(manifest, state, promise=promise, category=category, status=status, search=search)
    ]
    if limit is not None:
        matches = matches[:limit]
    payload = {
        "status": "ok",
        "count": len(matches),
        "filters": {
            "promise": promise,
            "category": category,
            "status": status,
            "search": search,
            "limit": limit,
        },
        "items": matches,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_stats(
    root: Path,
    *,
    promise: str | None,
    category: str | None,
    status: str | None,
    search: str | None,
    limit: int | None,
) -> int:
    manifest, state = load_review_context(root)
    matches = filtered_items(manifest, state, promise=promise, category=category, status=status, search=search)
    promise_counts = Counter(item["promise"] for item in matches)
    category_counts = Counter(item["category"] for item in matches)
    effective_status_counts = Counter(effective_status(item, state) or "unmarked" for item in matches)

    top_categories = [
        {"category": category_name, "count": count}
        for category_name, count in category_counts.most_common(limit)
    ] if limit is not None else [
        {"category": category_name, "count": count}
        for category_name, count in category_counts.most_common()
    ]

    payload = {
        "status": "ok",
        "count": len(matches),
        "filters": {
            "promise": promise,
            "category": category,
            "status": status,
            "search": search,
            "limit": limit,
        },
        "promiseCounts": dict(promise_counts),
        "effectiveStatusCounts": dict(effective_status_counts),
        "topCategories": top_categories,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_report(root: Path, *, limit: int | None) -> int:
    manifest, state = load_review_context(root)
    payload = build_report_payload(manifest, state, effective_status_fn=effective_status, root=str(root), limit=limit)
    print(json.dumps(payload, ensure_ascii=False))
    return 0
