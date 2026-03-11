"""Per-user daily quota tracking based on actual LLM token cost (USD).

Reuses the same token_usage.db from token_tracker (shared connection + lock).
Only exposes fraction (0.0–1.0) to clients — never absolute numbers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .token_tracker import _get_conn, _lock

# Gemini pricing (USD per 1M tokens)
_INPUT_PER_M = 0.10
_OUTPUT_PER_M = 0.40
_EMBED_PER_M = 0.00025

PRO_DAILY_LIMIT_USD = 0.30
_ROLLING_WINDOW_SECONDS = 86400  # 24 h


def _token_cost_usd(call_type: str, input_tokens: int, output_tokens: int) -> float:
    if call_type == "embed":
        return (input_tokens / 1_000_000) * _EMBED_PER_M
    return (input_tokens / 1_000_000) * _INPUT_PER_M + (output_tokens / 1_000_000) * _OUTPUT_PER_M


def _used_usd(user_id: str) -> float:
    """Sum actual USD cost from token usage in the last 24 h."""
    cutoff = datetime.now(timezone.utc).timestamp() - _ROLLING_WINDOW_SECONDS
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

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
        total += _token_cost_usd(call_type, total_in or 0, total_out or 0)
    return total


def _reset_seconds() -> int:
    """Seconds until the oldest record in the window would expire (rough)."""
    return _ROLLING_WINDOW_SECONDS


def get_quota_state(user_id: str) -> dict:
    """Return {fraction, reset_seconds} where fraction = remaining / limit."""
    used = _used_usd(user_id)
    remaining = max(PRO_DAILY_LIMIT_USD - used, 0.0)
    fraction = round(remaining / PRO_DAILY_LIMIT_USD, 4)
    return {"fraction": fraction, "reset_seconds": _reset_seconds()}


def get_all_quota_usage() -> dict[str, dict]:
    """Return 24h quota usage for all users (admin only)."""
    cutoff = datetime.now(timezone.utc).timestamp() - _ROLLING_WINDOW_SECONDS
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

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
        cost = _token_cost_usd(call_type, total_in or 0, total_out or 0)
        result[user_id]["used_usd"] += cost
        result[user_id]["calls"][call_type] = {"count": cnt, "cost_usd": round(cost, 6)}

    for uid in result:
        used = result[uid]["used_usd"]
        result[uid]["used_usd"] = round(used, 6)
        result[uid]["fraction_used"] = round(used / PRO_DAILY_LIMIT_USD, 4)

    return result


def check_quota(user_id: str, call_type: str) -> dict:
    """Pre-flight check before a translate call.

    Returns {exceeded: bool, fraction, reset_seconds}.
    """
    used = _used_usd(user_id)
    exceeded = used >= PRO_DAILY_LIMIT_USD
    remaining = max(PRO_DAILY_LIMIT_USD - used, 0.0)
    fraction = round(remaining / PRO_DAILY_LIMIT_USD, 4)
    return {"exceeded": exceeded, "fraction": fraction, "reset_seconds": _reset_seconds()}
