#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

import json
from pathlib import Path

from catalog_review_cli_parser import build_parser, dispatch_command
from catalog_review_cli_queries import cmd_list, cmd_report, cmd_show, cmd_stats, cmd_summary
from catalog_review_cli_support import (
    effective_status,
    filtered_items,
    load_json,
    load_review_context,
    resolve_paths,
    write_json,
)
from catalog_review_doctor import build_doctor_payload, project_doctor_view
from catalog_review_repair import repair_review_state, summarize_repairs
from catalog_review_report import build_report_payload
from catalog_review_state import append_history
from catalog_review_sync import hydrate_manifest, write_review_outputs
from catalog_review_verify import verify_review_artifacts


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
def cmd_verify(root: Path) -> int:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    html_path = root / "review.html"
    html_text = html_path.read_text(encoding="utf-8")
    payload = {
        "manifest": str(manifest_path),
        "state": str(state_path),
        "html": str(html_path),
        **verify_review_artifacts(manifest, state, html_text),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "ok" else 1


def cmd_repair(root: Path, *, dry_run: bool, limit: int | None, include_repairs: bool) -> int:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    repaired_state, repairs = repair_review_state(manifest, state)
    hydrated_manifest = hydrate_manifest(manifest, repaired_state)
    repair_summary = summarize_repairs(repairs, limit=limit)
    payload = {
        "status": "ok",
        "dryRun": dry_run,
        "manifest": str(manifest_path),
        "state": str(state_path),
        "repairCount": repair_summary["repairCount"],
        "repairTypeCounts": repair_summary["repairTypeCounts"],
        "sampleRepairs": repair_summary["sampleRepairs"],
        "truncatedRepairCount": repair_summary["truncatedRepairCount"],
    }
    if include_repairs:
        payload["repairs"] = repairs
    if dry_run or not repairs:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    write_json(state_path, repaired_state)
    write_review_outputs(root, hydrated_manifest, repaired_state)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_doctor(root: Path, *, limit: int | None, mode: str) -> int:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    html_path = root / "review.html"
    html_text = html_path.read_text(encoding="utf-8")
    full_payload = {
        "manifest": str(manifest_path),
        "state": str(state_path),
        "html": str(html_path),
        **build_doctor_payload(
            manifest,
            state,
            html_text,
            effective_status_fn=effective_status,
            root=str(root),
            limit=limit,
        ),
    }
    payload = project_doctor_view(full_payload, mode=mode)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "ok" else 1


def cmd_doctor_shortcut(root: Path, *, limit: int | None, mode: str) -> int:
    return cmd_doctor(root, limit=limit, mode=mode)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()
    return dispatch_command(args, root, handlers={
        "summary": cmd_summary,
        "show": cmd_show,
        "mark": cmd_mark,
        "list": cmd_list,
        "apply": cmd_apply,
        "stats": cmd_stats,
        "report": cmd_report,
        "verify": cmd_verify,
        "repair": cmd_repair,
        "doctor": cmd_doctor,
        "shortcut": cmd_doctor_shortcut,
    }, parser=parser)


if __name__ == "__main__":
    raise SystemExit(main())
