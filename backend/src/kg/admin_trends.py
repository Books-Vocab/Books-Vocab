"""Site-wide 30-day trend aggregations for admin dashboard.

Reads existing log tables (no schema changes) and returns aligned daily
buckets (UTC date) suitable for sparkline rendering:

  - errors_per_day       : failed pipeline_runs + rejected judge entries
  - tokens_per_day       : daily token total + per-call_type breakdown
  - active_users_per_day : DISTINCT user_id from token_usage per day

All series are length-aligned to ``len(days) == window_days`` (default 30,
oldest first) so the UI can zip them without bounds checks. Empty days are
filled with zeros / empty dicts so charts don't sag.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 90


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _date_range(window_days: int) -> list[date]:
    today = _utcnow().date()
    start = today - timedelta(days=window_days - 1)
    return [start + timedelta(days=i) for i in range(window_days)]


def _cutoff_iso(start_date: date) -> str:
    return datetime.combine(start_date, datetime.min.time(), tzinfo=UTC).isoformat()


# ---------------------------------------------------------------------------
# error series (pipeline failures + judge rejects)
# ---------------------------------------------------------------------------


def _pipeline_failures_by_day(cutoff_iso: str) -> dict[str, int]:
    """Count terminal-state runs with status='failed' per UTC date."""
    from . import pipeline_log as pl

    with pl._lock:
        conn = pl._get_conn()
        rows = conn.execute(
            "SELECT substr(started_at, 1, 10) AS d, COUNT(*) "
            "FROM pipeline_runs "
            "WHERE started_at >= ? AND status = 'failed' "
            "GROUP BY d",
            (cutoff_iso,),
        ).fetchall()
    return {d: int(c or 0) for d, c in rows if d}


def _judge_rejects_by_day(cutoff_iso: str) -> dict[str, int]:
    """Count auto-judge rejections per UTC date (treated as errors)."""
    from . import judge_log as jl

    if not jl.DB_PATH.exists():
        return {}
    with jl._lock:
        conn = jl._get_conn()
        rows = conn.execute(
            "SELECT substr(created_at, 1, 10) AS d, COUNT(*) "
            "FROM judge_log "
            "WHERE created_at >= ? AND source = 'auto' AND accepted = 0 "
            "GROUP BY d",
            (cutoff_iso,),
        ).fetchall()
    return {d: int(c or 0) for d, c in rows if d}


# ---------------------------------------------------------------------------
# token series (per call_type + total)
# ---------------------------------------------------------------------------


def _tokens_by_day_and_type(cutoff_iso: str) -> dict[str, dict[str, int]]:
    """Return {date_iso: {call_type: tokens (in+out)}}."""
    from . import token_tracker as tt

    with tt._lock:
        conn = tt._get_conn()
        rows = conn.execute(
            "SELECT substr(created_at, 1, 10) AS d, call_type, "
            "       SUM(input_tokens) AS ti, SUM(output_tokens) AS to_ "
            "FROM token_usage "
            "WHERE created_at >= ? "
            "GROUP BY d, call_type",
            (cutoff_iso,),
        ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for d, ct, ti, to_ in rows:
        if not d:
            continue
        bucket = out.setdefault(d, {})
        bucket[ct or "unknown"] = bucket.get(ct or "unknown", 0) + int(ti or 0) + int(to_ or 0)
    return out


def _active_users_by_day(cutoff_iso: str) -> dict[str, int]:
    """Return {date_iso: distinct user count from token_usage}."""
    from . import token_tracker as tt

    with tt._lock:
        conn = tt._get_conn()
        rows = conn.execute(
            "SELECT substr(created_at, 1, 10) AS d, COUNT(DISTINCT user_id) "
            "FROM token_usage "
            "WHERE created_at >= ? "
            "GROUP BY d",
            (cutoff_iso,),
        ).fetchall()
    return {d: int(c or 0) for d, c in rows if d}


# ---------------------------------------------------------------------------
# public entrypoint
# ---------------------------------------------------------------------------


def collect_trends(window_days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
    """Aggregate 30-day (default) daily trends across log tables.

    Returns aligned arrays:
      - days[i]                 ↔ errors_per_day[i]
                                ↔ tokens_per_day[i]['total']
                                ↔ tokens_per_day[i]['<call_type>']
                                ↔ active_users_per_day[i]

    `tokens_per_day[i]` shape: {'date': 'YYYY-MM-DD', 'total': int, '<call_type>': int, ...}
    """
    window_days = max(1, min(int(window_days or DEFAULT_WINDOW_DAYS), MAX_WINDOW_DAYS))
    days = _date_range(window_days)
    cutoff_iso = _cutoff_iso(days[0])

    pipe_fail = _pipeline_failures_by_day(cutoff_iso)
    judge_rej = _judge_rejects_by_day(cutoff_iso)
    tokens_map = _tokens_by_day_and_type(cutoff_iso)
    actives = _active_users_by_day(cutoff_iso)

    # Stable union of call_types seen in window — for legend stability
    call_types = sorted({ct for day in tokens_map.values() for ct in day.keys()})

    days_iso = [d.isoformat() for d in days]
    errors_per_day = [pipe_fail.get(d, 0) + judge_rej.get(d, 0) for d in days_iso]
    active_users_per_day = [actives.get(d, 0) for d in days_iso]

    tokens_per_day: list[dict[str, Any]] = []
    for d in days_iso:
        per_type = tokens_map.get(d, {})
        entry: dict[str, Any] = {"date": d}
        total = 0
        for ct in call_types:
            v = int(per_type.get(ct, 0))
            entry[ct] = v
            total += v
        entry["total"] = total
        tokens_per_day.append(entry)

    return {
        "window_days": window_days,
        "days": days_iso,
        "errors_per_day": errors_per_day,
        "tokens_per_day": tokens_per_day,
        "active_users_per_day": active_users_per_day,
        "call_types": call_types,
        "generated_at": _utcnow().isoformat(),
    }
