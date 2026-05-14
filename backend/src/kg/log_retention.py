"""Log-retention pruner for the 4 SQLite log singletons.

Each ``prune_*`` function deletes rows older than ``days`` from a single
log database and returns ``(deleted_count, remaining_count)``. The pruners
go through the existing module-level connection singletons so they respect
the test ``KG_DATA_DIR`` redirection and never bypass schema migrations.

A CLI entry point exposes the same operations for cron usage:

    uv run python -m kg.log_retention --all
    uv run python -m kg.log_retention --pipeline --days 30
    uv run python -m kg.log_retention --judge --translate
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

from . import judge_log, pipeline_log, token_tracker, translate_log

# Default retention windows (days). These match the brief.
DEFAULT_DAYS_PIPELINE = 30
DEFAULT_DAYS_JUDGE = 60
DEFAULT_DAYS_TRANSLATE = 14
DEFAULT_DAYS_TOKEN = 90


def _cutoff(days: int) -> str:
    """Return ISO8601 UTC cutoff timestamp for ``days`` ago.

    All log databases store timestamps as ISO8601 UTC strings, which sort
    lexicographically — so a plain ``WHERE col < cutoff`` is correct.
    """
    if days < 0:
        raise ValueError("days must be >= 0")
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _delete_and_count(conn, table: str, column: str, cutoff: str) -> tuple[int, int]:
    cur = conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
    deleted = cur.rowcount or 0
    conn.commit()
    remaining = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return deleted, remaining


# ─────────────────────────────────────────────────────────────────────────────
# Per-DB pruners
# ─────────────────────────────────────────────────────────────────────────────


def prune_pipeline_log(days: int = DEFAULT_DAYS_PIPELINE) -> tuple[int, int]:
    """Delete pipeline_runs rows whose ``started_at`` is older than ``days``."""
    cutoff = _cutoff(days)
    with pipeline_log._lock:
        conn = pipeline_log._get_conn()
        return _delete_and_count(conn, "pipeline_runs", "started_at", cutoff)


def prune_judge_log(days: int = DEFAULT_DAYS_JUDGE) -> tuple[int, int]:
    """Delete judge_log rows whose ``created_at`` is older than ``days``."""
    cutoff = _cutoff(days)
    with judge_log._lock:
        conn = judge_log._get_conn()
        return _delete_and_count(conn, "judge_log", "created_at", cutoff)


def prune_translate_log(days: int = DEFAULT_DAYS_TRANSLATE) -> tuple[int, int]:
    """Delete translate_log rows whose ``created_at`` is older than ``days``."""
    cutoff = _cutoff(days)
    with translate_log._lock:
        conn = translate_log._get_conn()
        return _delete_and_count(conn, "translate_log", "created_at", cutoff)


def prune_token_usage(days: int = DEFAULT_DAYS_TOKEN) -> tuple[int, int]:
    """Delete token_usage rows whose ``created_at`` is older than ``days``."""
    cutoff = _cutoff(days)
    with token_tracker._lock:
        conn = token_tracker._get_conn()
        return _delete_and_count(conn, "token_usage", "created_at", cutoff)


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate
# ─────────────────────────────────────────────────────────────────────────────


def run_all(
    *,
    pipeline_days: int = DEFAULT_DAYS_PIPELINE,
    judge_days: int = DEFAULT_DAYS_JUDGE,
    translate_days: int = DEFAULT_DAYS_TRANSLATE,
    token_days: int = DEFAULT_DAYS_TOKEN,
) -> dict[str, dict[str, int]]:
    """Run every pruner and return a structured report."""
    report: dict[str, dict[str, int]] = {}

    deleted, remaining = prune_pipeline_log(pipeline_days)
    report["pipeline_log"] = {"deleted": deleted, "remaining": remaining, "days": pipeline_days}

    deleted, remaining = prune_judge_log(judge_days)
    report["judge_log"] = {"deleted": deleted, "remaining": remaining, "days": judge_days}

    deleted, remaining = prune_translate_log(translate_days)
    report["translate_log"] = {"deleted": deleted, "remaining": remaining, "days": translate_days}

    deleted, remaining = prune_token_usage(token_days)
    report["token_usage"] = {"deleted": deleted, "remaining": remaining, "days": token_days}

    return report


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kg.log_retention",
        description="Prune old rows from KG log SQLite databases.",
    )
    parser.add_argument("--all", action="store_true", help="Prune every log DB (uses default retention windows).")
    parser.add_argument("--pipeline", action="store_true", help="Prune pipeline_runs.db.")
    parser.add_argument("--judge", action="store_true", help="Prune judge_log.db.")
    parser.add_argument("--translate", action="store_true", help="Prune translate_log.db.")
    parser.add_argument("--token", action="store_true", help="Prune token_usage.db.")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Override retention window (days). Applies to every selected target.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout.")
    return parser


def _run_from_args(args: argparse.Namespace) -> dict[str, dict[str, int]]:
    report: dict[str, dict[str, int]] = {}

    if args.all:
        return run_all(
            pipeline_days=args.days if args.days is not None else DEFAULT_DAYS_PIPELINE,
            judge_days=args.days if args.days is not None else DEFAULT_DAYS_JUDGE,
            translate_days=args.days if args.days is not None else DEFAULT_DAYS_TRANSLATE,
            token_days=args.days if args.days is not None else DEFAULT_DAYS_TOKEN,
        )

    if args.pipeline:
        d, r = prune_pipeline_log(args.days if args.days is not None else DEFAULT_DAYS_PIPELINE)
        report["pipeline_log"] = {"deleted": d, "remaining": r,
                                  "days": args.days if args.days is not None else DEFAULT_DAYS_PIPELINE}
    if args.judge:
        d, r = prune_judge_log(args.days if args.days is not None else DEFAULT_DAYS_JUDGE)
        report["judge_log"] = {"deleted": d, "remaining": r,
                               "days": args.days if args.days is not None else DEFAULT_DAYS_JUDGE}
    if args.translate:
        d, r = prune_translate_log(args.days if args.days is not None else DEFAULT_DAYS_TRANSLATE)
        report["translate_log"] = {"deleted": d, "remaining": r,
                                   "days": args.days if args.days is not None else DEFAULT_DAYS_TRANSLATE}
    if args.token:
        d, r = prune_token_usage(args.days if args.days is not None else DEFAULT_DAYS_TOKEN)
        report["token_usage"] = {"deleted": d, "remaining": r,
                                 "days": args.days if args.days is not None else DEFAULT_DAYS_TOKEN}

    return report


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not (args.all or args.pipeline or args.judge or args.translate or args.token):
        parser.print_help(sys.stderr)
        return 2

    report = _run_from_args(args)

    if args.json:
        print(json.dumps(report))
    else:
        for name, info in report.items():
            print(f"{name}: deleted={info['deleted']} remaining={info['remaining']} (>{info['days']}d)")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
