"""Pure dictionary lookup observability for the readonly ops CLI."""

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
from kg.ops_shared import connect_ro, data_dir, emit_json, print_table


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
    cutoff = now - timedelta(hours=window_hours)
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
            by_operation: dict[str, int] = {}
            events = []
            for row in conn.execute(
                "SELECT outcome, operation, duration_ms, created_at "
                "FROM lexical_lookup_event"
            ):
                created_at = _parse_utc(row[3])
                if created_at is not None and created_at >= cutoff:
                    events.append(row)
                    operation = str(row[1])
                    by_operation[operation] = by_operation.get(operation, 0) + 1
            for outcome, _, _, _ in events:
                by_outcome[str(outcome)] = by_outcome.get(str(outcome), 0) + 1
            latencies = sorted(
                int(duration_ms or 0)
                for _, _, duration_ms, _ in events
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
