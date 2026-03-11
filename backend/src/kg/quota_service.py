"""Per-user daily quota tracking for translate endpoints.

Reuses the same token_usage.db from token_tracker (shared connection + lock).
Only exposes fraction (0.0–1.0) to clients — never absolute numbers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .token_tracker import _get_conn, _lock

# Cost per call type (abstract "points", not real money).
CALL_COST: dict[str, int] = {
    "translate_quick": 2,
    "translate_phrase": 2,
    "translate_explain": 5,
}

PRO_DAILY_LIMIT = 300
_ROLLING_WINDOW_SECONDS = 86400  # 24 h


def _used_points(user_id: str) -> int:
    """Sum cost-weighted calls in the last 24 h."""
    cutoff = datetime.now(timezone.utc).timestamp() - _ROLLING_WINDOW_SECONDS
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT call_type, COUNT(*) AS cnt
            FROM token_usage
            WHERE user_id = ? AND created_at >= ?
            GROUP BY call_type
            """,
            (user_id, cutoff_iso),
        ).fetchall()

    total = 0
    for call_type, cnt in rows:
        total += cnt * CALL_COST.get(call_type, 0)
    return total


def _reset_seconds() -> int:
    """Seconds until the oldest record in the window would expire (rough)."""
    return _ROLLING_WINDOW_SECONDS


def get_quota_state(user_id: str) -> dict:
    """Return {fraction, reset_seconds} where fraction = remaining / limit."""
    used = _used_points(user_id)
    remaining = max(PRO_DAILY_LIMIT - used, 0)
    fraction = round(remaining / PRO_DAILY_LIMIT, 4)
    return {"fraction": fraction, "reset_seconds": _reset_seconds()}


def check_quota(user_id: str, call_type: str) -> dict:
    """Pre-flight check before a translate call.

    Returns {exceeded: bool, fraction, reset_seconds}.
    """
    used = _used_points(user_id)
    cost = CALL_COST.get(call_type, 0)
    exceeded = (used + cost) > PRO_DAILY_LIMIT
    remaining = max(PRO_DAILY_LIMIT - used, 0)
    fraction = round(remaining / PRO_DAILY_LIMIT, 4)
    return {"exceeded": exceeded, "fraction": fraction, "reset_seconds": _reset_seconds()}
