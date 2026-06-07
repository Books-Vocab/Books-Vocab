from __future__ import annotations

import argparse
from pathlib import Path

from catalog_review_doctor import DOCTOR_MODES


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


def dispatch_command(args: argparse.Namespace, root: Path, *, handlers: dict[str, callable], parser: argparse.ArgumentParser) -> int:
    command = args.command
    if command == "summary":
        return handlers["summary"](root)
    if command == "show":
        return handlers["show"](root, args.asset_id)
    if command == "mark":
        return handlers["mark"](root, args.asset_id, args.status, args.note)
    if command == "list":
        return handlers["list"](
            root,
            promise=args.promise,
            category=args.category,
            status=args.status,
            search=args.search,
            limit=args.limit,
        )
    if command == "apply":
        return handlers["apply"](
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
    if command == "stats":
        return handlers["stats"](
            root,
            promise=args.promise,
            category=args.category,
            status=args.status,
            search=args.search,
            limit=args.limit,
        )
    if command == "report":
        return handlers["report"](root, limit=args.limit)
    if command == "verify":
        return handlers["verify"](root)
    if command == "repair":
        return handlers["repair"](root, dry_run=args.dry_run, limit=args.limit, include_repairs=args.include_repairs)
    if command == "doctor":
        return handlers["doctor"](root, limit=args.limit, mode=args.mode)
    if command == "hero":
        return handlers["shortcut"](root, limit=args.limit, mode="hero-first")
    if command == "coverage":
        return handlers["shortcut"](root, limit=args.limit, mode="coverage-first")
    if command == "cleanup":
        return handlers["shortcut"](root, limit=args.limit, mode="cleanup")
    parser.error(f"unknown command: {command}")
    return 2
