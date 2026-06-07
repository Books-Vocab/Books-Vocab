from __future__ import annotations

import json
from pathlib import Path

from catalog_review_cli_support import (
    build_filter_payload,
    effective_status,
    find_item_by_asset_id,
    filtered_items,
    load_review_context,
    resolve_paths,
    serialize_review_item,
    write_json,
)
from catalog_review_state import update_review_entry
from catalog_review_sync import write_review_outputs


VALID_STATUSES = {"shortlist", "review", "reject", ""}


def cmd_mark(root: Path, asset_id: str, status: str, note: str | None) -> int:
    if status not in VALID_STATUSES:
        print(json.dumps({"status": "error", "error": "invalid-status", "allowed": sorted(VALID_STATUSES)}, ensure_ascii=False))
        return 2
    manifest_path, state_path = resolve_paths(root)
    manifest, state = load_review_context(root)
    item = find_item_by_asset_id(manifest, asset_id)
    if item is None:
        print(json.dumps({"status": "error", "error": "asset-not-found", "assetID": asset_id}, ensure_ascii=False))
        return 1
    entry = update_review_entry(
        state["entries"],
        item,
        asset_id=asset_id,
        status=status,
        note=note,
        action="mark",
    )
    write_json(state_path, state)
    write_review_outputs(root, manifest, state)
    print(json.dumps({"status": "ok", "assetID": asset_id, "reviewStatus": status, "note": entry["note"]}, ensure_ascii=False))
    return 0


def cmd_apply(
    root: Path,
    *,
    promise: str | None,
    category: str | None,
    match_status: str | None,
    search: str | None,
    target_status: str,
    note: str | None,
    limit: int | None,
    dry_run: bool,
) -> int:
    if target_status not in VALID_STATUSES:
        print(json.dumps({"status": "error", "error": "invalid-status", "allowed": sorted(VALID_STATUSES)}, ensure_ascii=False))
        return 2

    manifest_path, state_path = resolve_paths(root)
    manifest, state = load_review_context(root)
    matches = filtered_items(manifest, state, promise=promise, category=category, status=match_status, search=search)
    if limit is not None:
        matches = matches[:limit]

    payload = {
        "status": "ok",
        "dryRun": dry_run,
        "appliedCount": len(matches),
        "targetStatus": target_status,
        "filters": build_filter_payload(
            promise=promise,
            category=category,
            status=match_status,
            search=search,
            limit=limit,
            status_key="matchStatus",
        ),
        "items": [
            serialize_review_item(root, item, state, include_updated_at=True)
            for item in matches
        ],
    }
    if dry_run or not matches:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    for item in matches:
        update_review_entry(
            state["entries"],
            item,
            asset_id=item["assetID"],
            status=target_status,
            note=note,
            action="apply",
        )

    write_json(state_path, state)
    write_review_outputs(root, manifest, state)
    print(json.dumps(payload, ensure_ascii=False))
    return 0
