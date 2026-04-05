"""Per-user daily quota tracking based on actual LLM token cost (USD).

Reuses the same token_usage.db from token_tracker (shared connection + lock).
Only exposes fraction (0.0–1.0) to clients — never absolute numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .token_tracker import _get_conn, _lock

# Gemini pricing (USD per 1M tokens)
INPUT_PER_M = 0.10
OUTPUT_PER_M = 0.40
EMBED_PER_M = 0.00025

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
    if call_type == "embed":
        return (input_tokens / 1_000_000) * EMBED_PER_M
    return (input_tokens / 1_000_000) * INPUT_PER_M + (output_tokens / 1_000_000) * OUTPUT_PER_M


def _used_usd(user_id: str) -> float:
    """Sum actual USD cost from token usage in the last 24 h."""
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
    return total


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
