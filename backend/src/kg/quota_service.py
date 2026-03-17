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

PRO_DAILY_LIMIT_USD = 0.30
FREE_DAILY_LIMIT_USD = 0.03
_ROLLING_WINDOW_SECONDS = 86400  # 24 h


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
