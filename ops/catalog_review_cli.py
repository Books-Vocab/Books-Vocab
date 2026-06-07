#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from catalog_review_sync import hydrate_manifest, write_review_outputs


VALID_STATUSES = {"shortlist", "review", "reject", ""}
PROMISE_ORDER = ["Read", "Connect", "Retain", "Continue", "Weak"]


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
    by_promise: dict[str, dict] = defaultdict(
        lambda: {
            "total": 0,
            "shortlist": 0,
            "review": 0,
            "reject": 0,
            "unmarked": 0,
            "heroTotal": 0,
            "heroUnmarked": 0,
            "unmarkedCategories": Counter(),
        }
    )

    for item in manifest["items"]:
        promise = item["promise"]
        bucket = by_promise[promise]
        bucket["total"] += 1
        effective = effective_status(item, state) or "unmarked"
        bucket[effective] += 1
        if item.get("heroCandidate"):
            bucket["heroTotal"] += 1
            if effective == "unmarked":
                bucket["heroUnmarked"] += 1
        if effective == "unmarked":
            bucket["unmarkedCategories"][item["category"]] += 1

    promise_report = []
    next_actions = []
    for promise in PROMISE_ORDER:
        if promise not in by_promise:
            continue
        bucket = by_promise[promise]
        top_unmarked = [
            {"category": category, "count": count}
            for category, count in bucket["unmarkedCategories"].most_common(limit)
        ] if limit is not None else [
            {"category": category, "count": count}
            for category, count in bucket["unmarkedCategories"].most_common()
        ]
        promise_report.append(
            {
                "promise": promise,
                "total": bucket["total"],
                "shortlist": bucket["shortlist"],
                "review": bucket["review"],
                "reject": bucket["reject"],
                "unmarked": bucket["unmarked"],
                "heroTotal": bucket["heroTotal"],
                "heroUnmarked": bucket["heroUnmarked"],
                "topUnmarkedCategories": top_unmarked,
            }
        )
        if bucket["heroUnmarked"] > 0:
            next_actions.append({
                "kind": "hero-unmarked",
                "promise": promise,
                "count": bucket["heroUnmarked"],
                "command": (
                    f"./ops/catalog_review_cli.py {root} list --promise {promise} --search hero --limit {limit or 10}"
                ),
            })
        if top_unmarked:
            top_category = top_unmarked[0]["category"]
            next_actions.append({
                "kind": "top-unmarked-category",
                "promise": promise,
                "category": top_category,
                "count": top_unmarked[0]["count"],
                "command": (
                    f"./ops/catalog_review_cli.py {root} apply --promise {promise} --category '{top_category}' "
                    f"--status review --limit {limit or 10} --dry-run"
                ),
            })

    payload = {
        "status": "ok",
        "totalImages": manifest["totalImages"],
        "stateCounts": manifest.get("stateCounts", {}),
        "promises": promise_report,
        "nextActions": next_actions,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


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
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
