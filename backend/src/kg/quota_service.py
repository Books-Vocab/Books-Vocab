"""Per-user daily quota tracking based on actual LLM token cost (USD).

Reuses the same token_usage.db from token_tracker (shared connection + lock).
Only exposes fraction (0.0–1.0) to clients — never absolute numbers.
"""

from __future__ import annotations

import itertools
import threading
from contextlib import contextmanager
from datetime import UTC, datetime

from .llm.providers import REGISTRY, provider_for
from .token_tracker import _get_conn, _lock

# Gemini reference pricing (USD per 1M tokens). Per-call cost is computed
# provider-aware in token_cost_usd(); these constants are the gemini baseline
# surfaced by the admin cost views.
_GEMINI = REGISTRY["gemini"]
INPUT_PER_M = _GEMINI.input_price_per_m
OUTPUT_PER_M = _GEMINI.output_price_per_m
EMBED_PER_M = _GEMINI.embed_price_per_m

# Defaults; overridden at runtime via configure_limits() from app startup.
# Canonical values live in KGSettings (settings.py); these are only fallbacks
# for the brief window before configure_limits() runs.
PRO_DAILY_LIMIT_USD: float = 0.30
FREE_DAILY_LIMIT_USD: float = 0.03
_ROLLING_WINDOW_SECONDS = 86400  # 24 h


def configure_limits(*, pro: float, free: float) -> None:
    """Called from app startup to sync limits with KGSettings."""
    global PRO_DAILY_LIMIT_USD, FREE_DAILY_LIMIT_USD
    PRO_DAILY_LIMIT_USD = pro
    FREE_DAILY_LIMIT_USD = free


def _daily_limit(is_pro: bool) -> float:
    return PRO_DAILY_LIMIT_USD if is_pro else FREE_DAILY_LIMIT_USD


def token_cost_usd(call_type: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost of a recorded call, priced by the provider currently routed
    for its call_type.

    During a provider switch, up to ~24h of history is repriced at the new
    provider's rates — acceptable drift for a rolling quota window; exact
    historical pricing would need a per-row provider column.
    """
    provider = provider_for(call_type)
    if call_type == "embed":
        return (input_tokens / 1_000_000) * provider.embed_price_per_m
    return (
        (input_tokens / 1_000_000) * provider.input_price_per_m
        + (output_tokens / 1_000_000) * provider.output_price_per_m
    )


# Conservative per-call cost estimate (USD) held as an in-flight reservation
# while an LLM request is in progress. It only needs to be large enough that
# a burst of concurrent same-user calls can't all clear the gate before any
# real cost is recorded — it does NOT need to be accurate, because the real
# cost replaces it the instant `token_tracker.record()` lands. Chosen so a
# Free user ($0.03/day) admits ~2-3 in-flight calls, not an unbounded burst.
ESTIMATED_CALL_COST_USD: float = 0.012
ESTIMATED_EMBED_COST_USD: float = 0.0005


def estimate_call_cost(call_type: str) -> float:
    """Reservation estimate for a single LLM call of the given type."""
    return ESTIMATED_EMBED_COST_USD if call_type == "embed" else ESTIMATED_CALL_COST_USD


# ── In-flight reservation registry ───────────────────────────────────
#
# Why this exists: the quota gate (`check_quota`) is consulted BEFORE an
# LLM call, but `token_tracker.record()` only lands AFTER it completes.
# Concurrent same-user requests — multi-tab translate, or a single
# pipeline run fanning out 5-way enrich batches via ThreadPoolExecutor —
# all observe `used=0` and pass the gate before the first record() lands,
# producing unbounded over-spend (a Free user's $0.03/day budget is tiny).
#
# A reservation is an optimistic, in-memory estimate of an in-flight
# call's cost. The gate counts outstanding reservations on top of
# recorded usage; the reservation is released once the call finishes
# (its real cost is by then in token_usage.db). Purely process-local —
# no schema change, no new dependency. Cross-process workers still each
# enforce their own slice; the dominant concurrency (one Uvicorn worker,
# threadpool fan-out, asyncio tasks) is fully covered.
#
# DEPLOYMENT INVARIANT: correctness here depends on a single-worker
# deploy. With N workers each holds its own `_reservations`, so the
# effective over-spend ceiling becomes N × the real per-user limit.
# This is locked by Dockerfile's `--workers 1`; see also docs/dev/deploy.md.
# Scaling out requires moving reservations to shared storage (Redis/DB) first.

_reservations: dict[int, tuple[str, float]] = {}
_reservation_ids = itertools.count(1)
_reservation_lock = threading.Lock()


def _reserved_usd(user_id: str) -> float:
    """Sum of outstanding in-flight reservations for a user."""
    with _reservation_lock:
        return sum(cost for uid, cost in _reservations.values() if uid == user_id)


@contextmanager
def reserve(user_id: str, estimated_usd: float):
    """Hold an in-flight quota reservation for the duration of a call.

    Usage::

        with reserve(user["id"], estimate):
            result = llm_call()

    The reservation counts against the quota gate while held and is
    released on block exit — including when the body raises — so a
    failed handler never leaks budget.
    """
    if not user_id or estimated_usd <= 0:
        # Nothing to reserve; still yield so callers can wrap freely.
        yield
        return
    rid = next(_reservation_ids)
    with _reservation_lock:
        _reservations[rid] = (user_id, float(estimated_usd))
    try:
        yield
    finally:
        with _reservation_lock:
            _reservations.pop(rid, None)


def clear_reservations() -> None:
    """Drop all outstanding reservations (test isolation / shutdown)."""
    with _reservation_lock:
        _reservations.clear()


def _used_usd(user_id: str) -> float:
    """Recorded USD cost (last 24 h) PLUS outstanding in-flight reservations.

    Folding reservations in here means every quota reader — `check_quota`,
    `check_and_get_quota`, `get_quota_state` — defends the pre-flight gap
    without each having to know about reservations.
    """
    cutoff = datetime.now(UTC).timestamp() - _ROLLING_WINDOW_SECONDS
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()

    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT call_type, SUM(input_tokens) AS total_in, SUM(output_tokens) AS total_out
            FROM token_usage
            WHERE user_id = ? AND created_at >= ?
            GROUP BY call_type
            """,
            (user_id, cutoff_iso),
        ).fetchall()

    total = 0.0
    for call_type, total_in, total_out in rows:
        total += token_cost_usd(call_type, total_in or 0, total_out or 0)
    return total + _reserved_usd(user_id)


def _reset_seconds() -> int:
    """Seconds until the oldest record in the window would expire (rough)."""
    return _ROLLING_WINDOW_SECONDS


def get_quota_state(user_id: str, *, is_pro: bool = False) -> dict:
    """Return {fraction, reset_seconds} where fraction = remaining / limit."""
    limit = _daily_limit(is_pro)
    used = _used_usd(user_id)
    remaining = max(limit - used, 0.0)
    fraction = round(remaining / limit, 4)
    return {"fraction": fraction, "reset_seconds": _reset_seconds()}


def get_all_quota_usage() -> dict[str, dict]:
    """Return 24h quota usage for all users (admin only)."""
    cutoff = datetime.now(UTC).timestamp() - _ROLLING_WINDOW_SECONDS
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()

    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT user_id, call_type,
                   COUNT(*) AS cnt,
                   SUM(input_tokens) AS total_in,
                   SUM(output_tokens) AS total_out
            FROM token_usage
            WHERE created_at >= ?
            GROUP BY user_id, call_type
            """,
            (cutoff_iso,),
        ).fetchall()

    result: dict[str, dict] = {}
    for user_id, call_type, cnt, total_in, total_out in rows:
        if user_id not in result:
            result[user_id] = {"used_usd": 0.0, "limit_usd": PRO_DAILY_LIMIT_USD, "calls": {}}
        cost = token_cost_usd(call_type, total_in or 0, total_out or 0)
        result[user_id]["used_usd"] += cost
        result[user_id]["calls"][call_type] = {"count": cnt, "cost_usd": round(cost, 6)}

    for uid in result:
        used = result[uid]["used_usd"]
        result[uid]["used_usd"] = round(used, 6)
        result[uid]["fraction_used"] = round(used / PRO_DAILY_LIMIT_USD, 4)

    return result


def get_user_usage_range(user_id: str, *, since_iso: str | None = None) -> dict:
    """Return per-type usage (calls + cost + tokens) for a user, filtered by time range.

    If `since_iso` is None, returns all-time usage. Used by admin UI for range filter.
    """
    with _lock:
        conn = _get_conn()
        if since_iso is None:
            rows = conn.execute(
                """
                SELECT call_type,
                       COUNT(*)          AS cnt,
                       SUM(input_tokens) AS total_in,
                       SUM(output_tokens) AS total_out
                FROM token_usage
                WHERE user_id = ?
                GROUP BY call_type
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT call_type,
                       COUNT(*)          AS cnt,
                       SUM(input_tokens) AS total_in,
                       SUM(output_tokens) AS total_out
                FROM token_usage
                WHERE user_id = ? AND created_at >= ?
                GROUP BY call_type
                """,
                (user_id, since_iso),
            ).fetchall()

    calls: dict[str, dict] = {}
    tokens: dict[str, dict] = {}
    total_cost = 0.0
    total_calls = 0
    for call_type, cnt, total_in, total_out in rows:
        ti = int(total_in or 0)
        to = int(total_out or 0)
        cost = token_cost_usd(call_type, ti, to)
        calls[call_type] = {"count": int(cnt), "cost_usd": round(cost, 6)}
        tokens[call_type] = {"input_tokens": ti, "output_tokens": to}
        total_cost += cost
        total_calls += int(cnt)

    return {
        "calls": calls,
        "tokens": tokens,
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 6),
    }


def check_quota(user_id: str, call_type: str, *, is_pro: bool = False) -> dict:
    """Pre-flight check before a translate call.

    Returns {exceeded: bool, fraction, reset_seconds}.
    """
    limit = _daily_limit(is_pro)
    used = _used_usd(user_id)
    exceeded = used >= limit
    remaining = max(limit - used, 0.0)
    fraction = round(remaining / limit, 4)
    return {"exceeded": exceeded, "fraction": fraction, "reset_seconds": _reset_seconds()}


def check_and_get_quota(user_id: str, call_type: str, *, is_pro: bool = False) -> dict:
    """Pre-flight check + state in one query."""
    limit = _daily_limit(is_pro)
    used = _used_usd(user_id)
    remaining = max(limit - used, 0.0)
    fraction = round(remaining / limit, 4)
    exceeded = used >= limit
    return {
        "exceeded": exceeded,
        "fraction": fraction,
        "reset_seconds": _reset_seconds(),
    }
