from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from catalog_review_doctor import DOCTOR_MODES


def _add_limit_argument(parser: argparse.ArgumentParser, *, default: int | None) -> None:
    parser.add_argument("--limit", type=int, default=default)


def _add_filter_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_status: bool,
    status_name: str = "--status",
) -> None:
    parser.add_argument("--promise", default=None)
    parser.add_argument("--category", default=None)
    if include_status:
        parser.add_argument(status_name, default=None)
    parser.add_argument("--search", default=None)
    _add_limit_argument(parser, default=None)


def _register_shortcut(subparsers: argparse._SubParsersAction[argparse.ArgumentParser], name: str) -> None:
    shortcut = subparsers.add_parser(name)
    _add_limit_argument(shortcut, default=5)


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
    _add_filter_arguments(list_cmd, include_status=True)

    apply_cmd = subparsers.add_parser("apply")
    _add_filter_arguments(apply_cmd, include_status=True, status_name="--match-status")
    apply_cmd.add_argument("--status", required=True)
    apply_cmd.add_argument("--note", default=None)
    apply_cmd.add_argument("--dry-run", action="store_true")

    stats_cmd = subparsers.add_parser("stats")
    _add_filter_arguments(stats_cmd, include_status=True)

    report_cmd = subparsers.add_parser("report")
    _add_limit_argument(report_cmd, default=None)

    # Surface-level coverage query (machine face for the gallery's Coverage view):
    # "which shippable surfaces are missing which ship-critical states". Named
    # "gaps" to avoid the existing "coverage" shortcut (review-backlog doctor mode).
    gaps_cmd = subparsers.add_parser("gaps")
    gaps_cmd.add_argument("--lane", default=None)
    gaps_cmd.add_argument("--missing", default=None, help="only surfaces missing this state facet")
    gaps_cmd.add_argument("--feature", default=None)
    gaps_cmd.add_argument("--min-gap", type=int, default=1)
    _add_limit_argument(gaps_cmd, default=None)

    subparsers.add_parser("verify")

    repair_cmd = subparsers.add_parser("repair")
    repair_cmd.add_argument("--dry-run", action="store_true")
    _add_limit_argument(repair_cmd, default=20)
    repair_cmd.add_argument("--include-repairs", action="store_true")

    doctor_cmd = subparsers.add_parser("doctor")
    _add_limit_argument(doctor_cmd, default=5)
    doctor_cmd.add_argument("--mode", choices=sorted(DOCTOR_MODES), default="overview")

    for shortcut_name in ("hero", "coverage", "cleanup"):
        _register_shortcut(subparsers, shortcut_name)

    return parser


def dispatch_command(
    args: argparse.Namespace,
    root: Path,
    *,
    handlers: dict[str, Callable],
    parser: argparse.ArgumentParser,
) -> int:
    command = args.command
    dispatchers: dict[str, Callable[[], int]] = {
        "summary": lambda: handlers["summary"](root),
        "show": lambda: handlers["show"](root, args.asset_id),
        "mark": lambda: handlers["mark"](root, args.asset_id, args.status, args.note),
        "list": lambda: handlers["list"](
            root,
            promise=args.promise,
            category=args.category,
            status=args.status,
            search=args.search,
            limit=args.limit,
        ),
        "apply": lambda: handlers["apply"](
            root,
            promise=args.promise,
            category=args.category,
            match_status=args.match_status,
            search=args.search,
            target_status=args.status,
            note=args.note,
            limit=args.limit,
            dry_run=args.dry_run,
        ),
        "stats": lambda: handlers["stats"](
            root,
            promise=args.promise,
            category=args.category,
            status=args.status,
            search=args.search,
            limit=args.limit,
        ),
        "report": lambda: handlers["report"](root, limit=args.limit),
        "gaps": lambda: handlers["gaps"](
            root,
            lane=args.lane,
            missing=args.missing,
            feature=args.feature,
            min_gap=args.min_gap,
            limit=args.limit,
        ),
        "verify": lambda: handlers["verify"](root),
        "repair": lambda: handlers["repair"](
            root,
            dry_run=args.dry_run,
            limit=args.limit,
            include_repairs=args.include_repairs,
        ),
        "doctor": lambda: handlers["doctor"](root, limit=args.limit, mode=args.mode),
        "hero": lambda: handlers["shortcut"](root, limit=args.limit, mode="hero-first"),
        "coverage": lambda: handlers["shortcut"](root, limit=args.limit, mode="coverage-first"),
        "cleanup": lambda: handlers["shortcut"](root, limit=args.limit, mode="cleanup"),
    }
    if command in dispatchers:
        return dispatchers[command]()
    parser.error(f"unknown command: {command}")
    return 2
