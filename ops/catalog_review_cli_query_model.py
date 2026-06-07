from __future__ import annotations

from collections import Counter
from pathlib import Path

from catalog_review_cli_support import (
    effective_status,
    filtered_items,
    load_review_context,
    serialize_review_item,
)


def load_query_matches(
    root: Path,
    *,
    promise: str | None,
    category: str | None,
    status: str | None,
    search: str | None,
    limit: int | None,
    include_updated_at: bool = False,
) -> tuple[dict, dict, list[dict]]:
    manifest, state = load_review_context(root)
    matches = [
        serialize_review_item(root, item, state, include_updated_at=include_updated_at)
        for item in filtered_items(manifest, state, promise=promise, category=category, status=status, search=search)
    ]
    if limit is not None:
        matches = matches[:limit]
    return manifest, state, matches


def build_match_stats(matches: list[dict], *, limit: int | None) -> dict:
    promise_counts = Counter(item["promise"] for item in matches)
    category_counts = Counter(item["category"] for item in matches)
    effective_status_counts = Counter(item.get("effectiveStatus") or "unmarked" for item in matches)
    top_categories = [
        {"category": category_name, "count": count}
        for category_name, count in category_counts.most_common(limit)
    ] if limit is not None else [
        {"category": category_name, "count": count}
        for category_name, count in category_counts.most_common()
    ]
    return {
        "count": len(matches),
        "promiseCounts": dict(promise_counts),
        "effectiveStatusCounts": dict(effective_status_counts),
        "topCategories": top_categories,
    }
