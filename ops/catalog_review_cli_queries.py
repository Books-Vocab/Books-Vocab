from __future__ import annotations

import json
from pathlib import Path

from catalog_review_cli_artifacts import (
    build_artifact_refs,
    build_permalink,
    load_review_context,
    resolve_paths,
)
from catalog_review_cli_serialization import effective_status
from catalog_review_cli_query_model import build_match_stats, load_query_matches
from catalog_review_cli_filters import build_filter_payload
from catalog_review_cli_serialization import find_item_by_asset_id
from catalog_review_report import build_report_payload


def cmd_summary(root: Path) -> int:
    manifest_path, state_path = resolve_paths(root)
    manifest, state = load_review_context(root)
    payload = {
        "status": "ok",
        **build_artifact_refs(root),
        "totalImages": manifest["totalImages"],
        "stateEntries": len(state["entries"]),
        "promiseCounts": manifest["promiseCounts"],
        "stateCounts": manifest.get("stateCounts", {}),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_show(root: Path, asset_id: str) -> int:
    manifest, state = load_review_context(root)
    item = find_item_by_asset_id(manifest, asset_id)
    if item is None:
        print(json.dumps({"status": "error", "error": "asset-not-found", "assetID": asset_id}, ensure_ascii=False))
        return 1
    payload = {
        "status": "ok",
        "asset": item,
        "state": state["entries"].get(asset_id, {}),
        "history": state["entries"].get(asset_id, {}).get("history", []),
        "permalink": build_permalink(root, asset_id),
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
    _, _, matches = load_query_matches(
        root,
        promise=promise,
        category=category,
        status=status,
        search=search,
        limit=limit,
    )
    payload = {
        "status": "ok",
        "count": len(matches),
        "filters": build_filter_payload(
            promise=promise,
            category=category,
            status=status,
            search=search,
            limit=limit,
        ),
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
    _, _, matches = load_query_matches(
        root,
        promise=promise,
        category=category,
        status=status,
        search=search,
        limit=None,
    )
    stats = build_match_stats(matches, limit=limit)

    payload = {
        "status": "ok",
        **stats,
        "filters": build_filter_payload(
            promise=promise,
            category=category,
            status=status,
            search=search,
            limit=limit,
        ),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_report(root: Path, *, limit: int | None) -> int:
    manifest, state = load_review_context(root)
    payload = build_report_payload(manifest, state, effective_status_fn=effective_status, root=str(root), limit=limit)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_gaps(
    root: Path,
    *,
    lane: str | None,
    missing: str | None,
    feature: str | None,
    min_gap: int,
    limit: int | None,
) -> int:
    """Surface-level coverage query — the machine face of the gallery's Coverage
    view. Reads the surface index's lane-aware coverage fields directly so an
    agent can ask "which shippable surfaces are missing which ship-critical
    states" without parsing the whole manifest. Untracked lanes (building blocks,
    engineering-only harness) carry no coverage target and are never reported."""
    manifest, _ = load_review_context(root)
    tracked = [s for s in manifest.get("surfaces", []) if s.get("coverageTracked")]
    rows = []
    for surface in tracked:
        if lane and surface.get("lane") != lane:
            continue
        if feature and surface.get("feature") != feature:
            continue
        if missing and missing not in surface.get("missingFacets", []):
            continue
        if surface.get("coverageGap", 0) < min_gap:
            continue
        rows.append(surface)
    rows.sort(key=lambda s: (-s.get("coverageGap", 0), s.get("feature", ""), s.get("surface", "")))
    if limit is not None:
        rows = rows[:limit]
    payload = {
        "status": "ok",
        **build_artifact_refs(root),
        "filters": {"lane": lane, "missing": missing, "feature": feature, "minGap": min_gap, "limit": limit},
        "trackedSurfaceCount": len(tracked),
        "matchCount": len(rows),
        "totalGap": sum(s.get("coverageGap", 0) for s in rows),
        "surfaces": [
            {
                "surface": s["surface"],
                "feature": s["feature"],
                "lane": s["lane"],
                "coverageGap": s["coverageGap"],
                "missingFacets": s["missingFacets"],
                "facetsPresent": s["facetsPresent"],
                "expectedFacets": s["expectedFacets"],
                "sceneCount": s["sceneCount"],
            }
            for s in rows
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0
