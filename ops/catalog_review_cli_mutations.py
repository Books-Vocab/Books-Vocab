from __future__ import annotations

import json
from pathlib import Path

from catalog_review_cli_support import effective_status, filtered_items, load_review_context, resolve_paths, write_json
from catalog_review_state import append_history
from catalog_review_sync import write_review_outputs


VALID_STATUSES = {"shortlist", "review", "reject", ""}


def cmd_mark(root: Path, asset_id: str, status: str, note: str | None) -> int:
    if status not in VALID_STATUSES:
        print(json.dumps({"status": "error", "error": "invalid-status", "allowed": sorted(VALID_STATUSES)}, ensure_ascii=False))
        return 2
    manifest_path, state_path = resolve_paths(root)
    manifest, state = load_review_context(root)
    item = next((entry for entry in manifest["items"] if entry["assetID"] == asset_id), None)
    if item is None:
        print(json.dumps({"status": "error", "error": "asset-not-found", "assetID": asset_id}, ensure_ascii=False))
        return 1
    entry = state["entries"].setdefault(asset_id, {})
    entry.update({
        "status": status,
        "note": note if note is not None else entry.get("note", ""),
        "promise": item["promise"],
        "category": item["category"],
        "title": item["title"],
        "device": item["device"],
        "appearance": item["appearance"],
        "relPath": item["relPath"],
    })
    append_history(entry, action="mark", status=status, note=entry["note"])
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
        "filters": {
            "promise": promise,
            "category": category,
            "matchStatus": match_status,
            "search": search,
            "limit": limit,
        },
        "items": [
            {
                "assetID": item["assetID"],
                "category": item["category"],
                "title": item["title"],
                "effectiveStatus": effective_status(item, state),
                "updatedAt": state["entries"].get(item["assetID"], {}).get("updatedAt"),
                "permalink": f"file://{root / 'review.html'}#asset-{item['assetID']}",
            }
            for item in matches
        ],
    }
    if dry_run or not matches:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    for item in matches:
        entry = state["entries"].setdefault(item["assetID"], {})
        entry.update({
            "status": target_status,
            "note": note if note is not None else entry.get("note", ""),
            "promise": item["promise"],
            "category": item["category"],
            "title": item["title"],
            "device": item["device"],
            "appearance": item["appearance"],
            "relPath": item["relPath"],
        })
        append_history(entry, action="apply", status=target_status, note=entry["note"])

    write_json(state_path, state)
    write_review_outputs(root, manifest, state)
    print(json.dumps(payload, ensure_ascii=False))
    return 0
