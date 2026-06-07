#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from catalog_review_doctor import DOCTOR_MODES, build_doctor_payload, project_doctor_view
from catalog_review_repair import repair_review_state, summarize_repairs
from catalog_review_report import build_report_payload
from catalog_review_state import append_history
from catalog_review_sync import hydrate_manifest, write_review_outputs
from catalog_review_verify import verify_review_artifacts


VALID_STATUSES = {"shortlist", "review", "reject", ""}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_paths(root: Path) -> tuple[Path, Path]:
    manifest_path = root / "review_manifest.json"
    state_path = root / "review_state.json"
    return manifest_path, state_path


def load_review_context(root: Path) -> tuple[dict, dict]:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    return hydrate_manifest(manifest, state), state


def effective_status(item: dict, state: dict) -> str:
    return state["entries"].get(item["assetID"], {}).get("status") or item.get("reviewStatus", "")


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and update catalog review state sidecars.")
    parser.add_argument("root", type=Path, help="Directory containing review_manifest.json and review_state.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary")

    show = subparsers.add_parser("show")
    show.add_argument("asset_id")

    mark = subparsers.add_parser("mark")
    mark.add_argument("asset_id")
    mark.add_argument("--status", default="review")
    mark.add_argument("--note", default=None)

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument("--promise", default=None)
    list_cmd.add_argument("--category", default=None)
    list_cmd.add_argument("--status", default=None)
    list_cmd.add_argument("--search", default=None)
    list_cmd.add_argument("--limit", type=int, default=None)

    apply_cmd = subparsers.add_parser("apply")
    apply_cmd.add_argument("--promise", default=None)
    apply_cmd.add_argument("--category", default=None)
    apply_cmd.add_argument("--match-status", default=None)
    apply_cmd.add_argument("--search", default=None)
    apply_cmd.add_argument("--status", required=True)
    apply_cmd.add_argument("--note", default=None)
    apply_cmd.add_argument("--limit", type=int, default=None)
    apply_cmd.add_argument("--dry-run", action="store_true")

    stats_cmd = subparsers.add_parser("stats")
    stats_cmd.add_argument("--promise", default=None)
    stats_cmd.add_argument("--category", default=None)
    stats_cmd.add_argument("--status", default=None)
    stats_cmd.add_argument("--search", default=None)
    stats_cmd.add_argument("--limit", type=int, default=None)

    report_cmd = subparsers.add_parser("report")
    report_cmd.add_argument("--limit", type=int, default=None)

    subparsers.add_parser("verify")
    repair_cmd = subparsers.add_parser("repair")
    repair_cmd.add_argument("--dry-run", action="store_true")
    repair_cmd.add_argument("--limit", type=int, default=20)
    repair_cmd.add_argument("--include-repairs", action="store_true")
    doctor_cmd = subparsers.add_parser("doctor")
    doctor_cmd.add_argument("--limit", type=int, default=5)
    doctor_cmd.add_argument("--mode", choices=sorted(DOCTOR_MODES), default="overview")

    hero_cmd = subparsers.add_parser("hero")
    hero_cmd.add_argument("--limit", type=int, default=5)

    coverage_cmd = subparsers.add_parser("coverage")
    coverage_cmd.add_argument("--limit", type=int, default=5)

    cleanup_cmd = subparsers.add_parser("cleanup")
    cleanup_cmd.add_argument("--limit", type=int, default=5)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "summary":
        return cmd_summary(root)
    if args.command == "show":
        return cmd_show(root, args.asset_id)
    if args.command == "mark":
        return cmd_mark(root, args.asset_id, args.status, args.note)
    if args.command == "list":
        return cmd_list(
            root,
            promise=args.promise,
            category=args.category,
            status=args.status,
            search=args.search,
            limit=args.limit,
        )
    if args.command == "apply":
        return cmd_apply(
            root,
            promise=args.promise,
            category=args.category,
            match_status=args.match_status,
            search=args.search,
            target_status=args.status,
            note=args.note,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    if args.command == "stats":
        return cmd_stats(
            root,
            promise=args.promise,
            category=args.category,
            status=args.status,
            search=args.search,
            limit=args.limit,
        )
    if args.command == "report":
        return cmd_report(root, limit=args.limit)
    if args.command == "verify":
        return cmd_verify(root)
    if args.command == "repair":
        return cmd_repair(root, dry_run=args.dry_run, limit=args.limit, include_repairs=args.include_repairs)
    if args.command == "doctor":
        return cmd_doctor(root, limit=args.limit, mode=args.mode)
    if args.command == "hero":
        return cmd_doctor_shortcut(root, limit=args.limit, mode="hero-first")
    if args.command == "coverage":
        return cmd_doctor_shortcut(root, limit=args.limit, mode="coverage-first")
    if args.command == "cleanup":
        return cmd_doctor_shortcut(root, limit=args.limit, mode="cleanup")
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
