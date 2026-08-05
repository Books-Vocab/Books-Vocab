"""Dictionary-card observability commands for the readonly ops CLI.

Two planes, deliberately separate because they fail independently:

``dictionary-health``
    Global lookup plane — the shared ``lexical_cache.db``: cache composition,
    upstream provider budget headroom, and the ``lexical_lookup_event`` ledger
    (hit / miss / stale / throttled / 429 / error + latency).

``dictionary-cards``
    Per-user card plane — each ``users/<uid>/cards.db``: saved dictionary card
    counts, in-flight materialization sagas, and promotion failures.

Both are strictly readonly (``connect_ro``) and tolerate DBs that predate the
dictionary feature — a missing table reports zero, never a traceback.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime, timedelta

from kg.lexical import (
    CACHE_SERVED_OUTCOMES,
    DEFAULT_PROVIDER_HOURLY_LIMIT,
    LOOKUP_FAILURE_OUTCOMES,
    LOOKUP_OUTCOMES,
)
from kg.ops_shared import connect_ro, data_dir, emit_json, print_table, resolve_uid


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    """``{value: count}`` for one column, or ``{}`` when the table predates it."""
    if not _has_table(conn, table):
        return {}
    try:
        rows = conn.execute(
            f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}"  # noqa: S608
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(value): int(count or 0) for value, count in rows if value is not None}


def _percentile(sorted_values: list[int], fraction: float) -> int:
    if not sorted_values:
        return 0
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def _empty_health(cache_db, window_hours: int) -> dict:
    return {
        "cache_db": str(cache_db),
        "exists": False,
        "window_hours": window_hours,
        "cache": {
            "entries": 0,
            "positive": 0,
            "negative": 0,
            "fresh": 0,
            "expired": 0,
            "oldest_fetched_at": None,
            "newest_fetched_at": None,
        },
        "provider_budget": {
            "hourly_limit": DEFAULT_PROVIDER_HOURLY_LIMIT,
            "requests_last_hour": {},
            "headroom": {},
        },
        "lookups": {
            "total": 0,
            "by_outcome": {},
            "by_operation": {},
            "latency_ms": {"p50": 0, "p95": 0, "max": 0},
            "admitted": 0,
            "cache_hit_rate": None,
            "failure_rate": None,
        },
    }


def cmd_dictionary_health(args: argparse.Namespace) -> None:
    """字典 provider / cache / lookup outcome 健康（全域，唯讀）。"""
    window_hours = max(1, min(int(args.window), 24 * 90))
    cache_db = data_dir() / "lexical_cache.db"
    result = _empty_health(cache_db, window_hours)
    if not cache_db.exists():
        _emit_health(args, result)
        return

    result["exists"] = True
    now = datetime.now(UTC)
    cutoff = (now - timedelta(hours=window_hours)).isoformat()
    conn = connect_ro(cache_db)
    try:
        if _has_table(conn, "lexical_cache"):
            entries, negative, fresh, oldest, newest = conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN is_negative = 1 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END), "
                "MIN(fetched_at), MAX(fetched_at) FROM lexical_cache",
                (now.isoformat(),),
            ).fetchone()
            entries = int(entries or 0)
            negative = int(negative or 0)
            fresh = int(fresh or 0)
            result["cache"] = {
                "entries": entries,
                "positive": entries - negative,
                "negative": negative,
                "fresh": fresh,
                "expired": entries - fresh,
                "oldest_fetched_at": oldest,
                "newest_fetched_at": newest,
            }

        if _has_table(conn, "lexical_provider_request"):
            window_start = now.timestamp() - 3600.0
            per_provider = {
                str(provider): int(count or 0)
                for provider, count in conn.execute(
                    "SELECT provider, COUNT(*) FROM lexical_provider_request "
                    "WHERE requested_at > ? GROUP BY provider",
                    (window_start,),
                )
            }
            limit = DEFAULT_PROVIDER_HOURLY_LIMIT
            result["provider_budget"] = {
                "hourly_limit": limit,
                "requests_last_hour": per_provider,
                "headroom": {p: limit - c for p, c in per_provider.items()},
            }

        if _has_table(conn, "lexical_lookup_event"):
            by_outcome: dict[str, int] = {}
            for outcome, count in conn.execute(
                "SELECT outcome, COUNT(*) FROM lexical_lookup_event "
                "WHERE created_at >= ? GROUP BY outcome",
                (cutoff,),
            ):
                by_outcome[str(outcome)] = int(count or 0)
            by_operation = {
                str(operation): int(count or 0)
                for operation, count in conn.execute(
                    "SELECT operation, COUNT(*) FROM lexical_lookup_event "
                    "WHERE created_at >= ? GROUP BY operation",
                    (cutoff,),
                )
            }
            latencies = sorted(
                int(row[0] or 0)
                for row in conn.execute(
                    "SELECT duration_ms FROM lexical_lookup_event WHERE created_at >= ?",
                    (cutoff,),
                )
            )
            total = sum(by_outcome.values())
            # Throttled requests never reached the lookup, so they belong in
            # neither numerator nor denominator of a cache/provider rate.
            admitted = total - by_outcome.get("throttled", 0)
            cache_served = sum(by_outcome.get(o, 0) for o in CACHE_SERVED_OUTCOMES)
            failed = sum(by_outcome.get(o, 0) for o in LOOKUP_FAILURE_OUTCOMES)
            result["lookups"] = {
                "total": total,
                "by_outcome": by_outcome,
                "by_operation": by_operation,
                "latency_ms": {
                    "p50": _percentile(latencies, 0.50),
                    "p95": _percentile(latencies, 0.95),
                    "max": latencies[-1] if latencies else 0,
                },
                "admitted": admitted,
                "cache_hit_rate": round(cache_served / admitted, 4) if admitted else None,
                "failure_rate": round(failed / admitted, 4) if admitted else None,
            }
    finally:
        conn.close()
    _emit_health(args, result)


def _emit_health(args: argparse.Namespace, result: dict) -> None:
    if args.json:
        emit_json(result)
        return

    print(f"Dictionary health — {result['cache_db']}")
    if not result["exists"]:
        print("(cache DB not created yet — no lookup has been served)")
        return
    cache = result["cache"]
    print(f"\nCache — {cache['entries']} entries")
    print_table(
        ["Positive", "Negative", "Fresh", "Expired", "Oldest fetch", "Newest fetch"],
        [[
            cache["positive"], cache["negative"], cache["fresh"], cache["expired"],
            cache["oldest_fetched_at"] or "-", cache["newest_fetched_at"] or "-",
        ]],
    )

    budget = result["provider_budget"]
    print(f"\nProvider budget — hourly limit {budget['hourly_limit']}")
    print_table(
        ["Provider", "Last hour", "Headroom"],
        [
            [provider, count, budget["headroom"].get(provider, "-")]
            for provider, count in sorted(budget["requests_last_hour"].items())
        ],
    )

    lookups = result["lookups"]

    def _pct(value) -> str:
        return "n/a" if value is None else f"{value:.1%}"

    print(
        f"\nLookups — last {result['window_hours']}h  |  total {lookups['total']}"
        f"  |  admitted {lookups['admitted']}"
        f"  |  cache hit {_pct(lookups['cache_hit_rate'])}"
        f"  |  failure {_pct(lookups['failure_rate'])}"
    )
    # Print the full vocabulary so a zero is visibly zero, not merely absent.
    print_table(
        ["Outcome", "Count"],
        [[outcome, lookups["by_outcome"].get(outcome, 0)] for outcome in LOOKUP_OUTCOMES],
    )
    latency = lookups["latency_ms"]
    print(
        f"\nLatency (ms) — p50 {latency['p50']}  p95 {latency['p95']}  max {latency['max']}"
    )
    refused = sum(
        lookups["by_outcome"].get(o, 0)
        for o in (*LOOKUP_FAILURE_OUTCOMES, "throttled")
    )
    if refused:
        print(f"\n⚠  {refused} refused/failed lookup(s) in window — see Outcome table")


def _user_dictionary_report(uid: str, cards_db) -> dict:
    conn = connect_ro(cards_db)
    try:
        cards = {"total": 0, "active": 0, "archived": 0, "deleted": 0, "reader_hidden": 0}
        promotion_state: dict[str, int] = {}
        if _has_table(conn, "card"):
            try:
                row = conn.execute(
                    "SELECT COUNT(*), "
                    "SUM(CASE WHEN is_archived = 0 AND is_deleted = 0 THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN is_archived = 1 AND is_deleted = 0 THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN is_deleted = 1 THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN reader_hidden = 1 THEN 1 ELSE 0 END) "
                    "FROM card WHERE card_role = 'dictionary'"
                ).fetchone()
                cards = {
                    "total": int(row[0] or 0),
                    "active": int(row[1] or 0),
                    "archived": int(row[2] or 0),
                    "deleted": int(row[3] or 0),
                    "reader_hidden": int(row[4] or 0),
                }
                promotion_state = {
                    str(state): int(count or 0)
                    for state, count in conn.execute(
                        "SELECT promotion_state, COUNT(*) FROM card "
                        "WHERE card_role = 'dictionary' GROUP BY promotion_state"
                    )
                }
            except sqlite3.OperationalError:
                # Pre-dictionary card table: no card_role/reader_hidden columns.
                pass

        sidecars = _counts(conn, "dictionary_entry", "materialization_status")
        operations = _counts(conn, "lexical_operations", "status")
        lifecycle_pending = _counts(conn, "dictionary_lifecycle_state", "pending_action")
        promotion_jobs = _counts(conn, "dictionary_promotion_jobs", "status")

        promotion_failures: list[dict] = []
        if _has_table(conn, "dictionary_promotion_jobs"):
            for card_id, error_code, retryable, attempts in conn.execute(
                "SELECT card_id, error_code, retryable, attempt_count "
                "FROM dictionary_promotion_jobs WHERE status = 'failed' "
                "ORDER BY updated_at DESC"
            ):
                promotion_failures.append(
                    {
                        "card_id": card_id,
                        "error_code": error_code,
                        "retryable": None if retryable is None else bool(retryable),
                        "attempt_count": int(attempts or 0),
                    }
                )
    finally:
        conn.close()

    return {
        "user_id": uid,
        "cards": cards,
        "promotion_state": promotion_state,
        "sidecars": sidecars,
        "operations": operations,
        # Anything not `completed` is a saga that has not converged. A non-zero
        # count that does not drain is the wedge signature worth paging on.
        "operations_in_flight": sum(
            count for status, count in operations.items() if status != "completed"
        ),
        "lifecycle_pending": lifecycle_pending,
        "promotion_jobs": promotion_jobs,
        "promotion_failures": promotion_failures,
    }


def cmd_dictionary_cards(args: argparse.Namespace) -> None:
    """字典卡 / staged operation / promotion 失敗盤點（單用戶或全用戶，唯讀）。"""
    root = data_dir()
    users_dir = root / "users"
    if args.uid == "all":
        uid_filter = None
        resolved = "all"
    else:
        uid_filter = resolve_uid(args.uid, root)
        resolved = uid_filter

    users: list[dict] = []
    if users_dir.exists():
        for entry in sorted(users_dir.iterdir()):
            if not entry.is_dir():
                continue
            if uid_filter is not None and entry.name != uid_filter:
                continue
            cards_db = entry / "cards.db"
            if not cards_db.exists():
                continue
            users.append(_user_dictionary_report(entry.name, cards_db))

    totals = {
        "users": len(users),
        "cards": sum(u["cards"]["total"] for u in users),
        "active_cards": sum(u["cards"]["active"] for u in users),
        "staged_sidecars": sum(u["sidecars"].get("staged", 0) for u in users),
        "operations_in_flight": sum(u["operations_in_flight"] for u in users),
        "lifecycle_pending": sum(sum(u["lifecycle_pending"].values()) for u in users),
        "promotion_failures": sum(len(u["promotion_failures"]) for u in users),
    }
    result = {"uid": resolved, "users": users, "totals": totals}

    if args.json:
        emit_json(result)
        return

    print(f"Dictionary cards — {resolved}  |  {totals['users']} user(s) with a cards.db")
    print("\nCards")
    print_table(
        ["User", "Total", "Active", "Archived", "Deleted", "Reader hidden"],
        [
            [
                u["user_id"], u["cards"]["total"], u["cards"]["active"],
                u["cards"]["archived"], u["cards"]["deleted"], u["cards"]["reader_hidden"],
            ]
            for u in users
        ],
    )
    print("\nOperations (staged materialization sagas)")
    print_table(
        ["User", "Staged sidecars", "In flight", "By status", "Lifecycle pending"],
        [
            [
                u["user_id"], u["sidecars"].get("staged", 0), u["operations_in_flight"],
                ", ".join(f"{k}={v}" for k, v in sorted(u["operations"].items())) or "-",
                ", ".join(f"{k}={v}" for k, v in sorted(u["lifecycle_pending"].items())) or "-",
            ]
            for u in users
        ],
    )
    print("\nPromotion")
    print_table(
        ["User", "Jobs by status", "Card promotion_state", "Failures"],
        [
            [
                u["user_id"],
                ", ".join(f"{k}={v}" for k, v in sorted(u["promotion_jobs"].items())) or "-",
                ", ".join(f"{k}={v}" for k, v in sorted(u["promotion_state"].items())) or "-",
                len(u["promotion_failures"]),
            ]
            for u in users
        ],
    )
    failures = [(u["user_id"], f) for u in users for f in u["promotion_failures"]]
    if failures:
        print(f"\n{len(failures)} promotion failure(s):")
        print_table(
            ["User", "Card", "Error", "Retryable", "Attempts"],
            [
                [uid, f["card_id"], f["error_code"] or "-", f["retryable"], f["attempt_count"]]
                for uid, f in failures
            ],
        )
    print(
        f"\nTOTAL — cards {totals['cards']} (active {totals['active_cards']})  |  "
        f"staged sidecars {totals['staged_sidecars']}  |  "
        f"in-flight ops {totals['operations_in_flight']}  |  "
        f"promotion failures {totals['promotion_failures']}"
    )
