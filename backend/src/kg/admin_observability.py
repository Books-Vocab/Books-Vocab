"""Site-wide observability aggregation for admin dashboard.

Aggregates metrics across all users by querying:
  - pipeline_runs.db (pipeline_log)  — failure rate, per-step p95 latency
  - judge_log.db                     — rejection rate
  - translate_log.db                 — cache hit rate
  - token_usage.db (token_tracker)   — daily token spend (7 days)

All aggregations use a 24h window, except daily_token_spend which uses 7 days.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _cutoff_iso(hours: int) -> str:
    return (_utcnow() - timedelta(hours=hours)).isoformat()


def _percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (no interpolation) for a list of numbers.

    pct is in [0, 100].  Returns None for empty input.
    """
    if not values:
        return None
    s = sorted(values)
    if pct <= 0:
        return s[0]
    if pct >= 100:
        return s[-1]
    # nearest-rank: rank = ceil(p/100 * N)
    rank = max(1, math.ceil(pct / 100.0 * len(s)))
    return s[rank - 1]


# ---------------------------------------------------------------------------
# pipeline_log aggregations
# ---------------------------------------------------------------------------


def _pipeline_failure_rate_24h() -> dict[str, Any]:
    """Count failed vs total pipeline runs in the last 24h.

    Excludes runs still 'running' (use ended runs only). A run counts in the
    window if its ``started_at`` falls within the 24h cutoff.
    """
    from . import pipeline_log as pl

    cutoff = _cutoff_iso(24)
    with pl._lock:
        conn = pl._get_conn()
        # Count terminal-state runs in window (exclude running/interrupted)
        row = conn.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed "
            "FROM pipeline_runs "
            "WHERE started_at >= ? AND status IN ('ok','failed')",
            (cutoff,),
        ).fetchone()
    total = (row[0] or 0) if row else 0
    failed = (row[1] or 0) if row else 0
    return {
        "total": total,
        "failed": failed,
        "rate": round(failed / total, 4) if total > 0 else None,
        "window_hours": 24,
    }


def _pipeline_step_p95_24h() -> dict[str, Any]:
    """Compute per-step p95 (ms) over the last 24h.

    Parses the ``steps`` JSON column from each run started in window. Skips
    steps without both ``started_at`` and ``ended_at``.
    """
    from . import pipeline_log as pl

    cutoff = _cutoff_iso(24)
    with pl._lock:
        conn = pl._get_conn()
        rows = conn.execute(
            "SELECT steps FROM pipeline_runs WHERE started_at >= ?",
            (cutoff,),
        ).fetchall()

    by_step: dict[str, list[float]] = {}
    for (steps_json,) in rows:
        try:
            steps = json.loads(steps_json or "[]")
        except json.JSONDecodeError:
            continue
        for step in steps:
            name = step.get("name")
            s_at = step.get("started_at")
            e_at = step.get("ended_at")
            if not name or not s_at or not e_at:
                continue
            try:
                s_dt = datetime.fromisoformat(s_at)
                e_dt = datetime.fromisoformat(e_at)
            except (ValueError, TypeError):
                continue
            dur_ms = (e_dt - s_dt).total_seconds() * 1000.0
            if dur_ms < 0:
                continue
            by_step.setdefault(name, []).append(dur_ms)

    steps_out = []
    for name, samples in by_step.items():
        p95 = _percentile(samples, 95.0)
        steps_out.append({
            "name": name,
            "count": len(samples),
            "p95_ms": round(p95, 1) if p95 is not None else None,
            "max_ms": round(max(samples), 1),
        })
    # sort descending by p95 so slowest steps surface first
    steps_out.sort(key=lambda d: (d["p95_ms"] or 0), reverse=True)
    return {"steps": steps_out, "window_hours": 24}


# ---------------------------------------------------------------------------
# judge_log aggregations
# ---------------------------------------------------------------------------


def _judge_rejection_rate_24h() -> dict[str, Any]:
    """Auto-judge rejection rate (source='auto') over the last 24h."""
    from . import judge_log as jl

    cutoff = _cutoff_iso(24)
    with jl._lock:
        conn = jl._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "       SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END) AS rejected "
            "FROM judge_log "
            "WHERE source='auto' AND created_at >= ?",
            (cutoff,),
        ).fetchone()
    total = (row[0] or 0) if row else 0
    rejected = (row[1] or 0) if row else 0
    return {
        "total": total,
        "rejected": rejected,
        "rate": round(rejected / total, 4) if total > 0 else None,
        "window_hours": 24,
    }


# ---------------------------------------------------------------------------
# translate_log aggregations
# ---------------------------------------------------------------------------


def _translate_cache_hit_rate_24h() -> dict[str, Any]:
    """Approximate cache hit rate over the last 24h.

    translate_log records *every* LLM call (cache misses) — successful cache
    hits short-circuit before record() so they are NOT in the table. Therefore
    we estimate the user-perceived hit rate as the fraction of *recorded*
    calls whose cache-key tuple already appeared at least once before this
    24h window or earlier in the window:

        hits  ≈ total_calls - distinct_keys
        rate  ≈ hits / total_calls

    This is a lower bound on actual hit rate (true hits never reach
    translate_log), and is the best signal available without a dedicated
    hit-counter table.
    """
    from . import translate_log as tl

    cutoff = _cutoff_iso(24)
    with tl._lock:
        conn = tl._get_conn()
        total_row = conn.execute(
            "SELECT COUNT(*) FROM translate_log WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
        distinct_row = conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT word, context_hash, source_lang, target_lang, operation "
            "  FROM translate_log "
            "  WHERE created_at >= ? "
            "  GROUP BY word, context_hash, source_lang, target_lang, operation"
            ")",
            (cutoff,),
        ).fetchone()
    total = (total_row[0] or 0) if total_row else 0
    distinct = (distinct_row[0] or 0) if distinct_row else 0
    hits = max(0, total - distinct)
    return {
        "total": total,
        "distinct": distinct,
        "hits": hits,
        "rate": round(hits / total, 4) if total > 0 else None,
        "window_hours": 24,
        "note": "lower-bound estimate from translate_log dedup; true cache hits short-circuit before recording",
    }


# ---------------------------------------------------------------------------
# token spend
# ---------------------------------------------------------------------------


def _daily_token_spend_7d() -> dict[str, Any]:
    """Per-day total tokens (input+output) for the last 7 UTC days.

    Returns 7 buckets aligned to UTC date (oldest first). Empty days are
    included with tokens=0 so charts stay aligned.
    """
    from . import token_tracker as tt

    today_utc = _utcnow().date()
    cutoff_date = today_utc - timedelta(days=6)  # 7 buckets inclusive
    cutoff_iso = datetime.combine(cutoff_date, datetime.min.time(), tzinfo=UTC).isoformat()

    with tt._lock:
        conn = tt._get_conn()
        rows = conn.execute(
            "SELECT substr(created_at, 1, 10) AS d, "
            "       SUM(input_tokens) AS ti, "
            "       SUM(output_tokens) AS to_ "
            "FROM token_usage "
            "WHERE created_at >= ? "
            "GROUP BY d "
            "ORDER BY d",
            (cutoff_iso,),
        ).fetchall()

    by_day: dict[str, dict[str, int]] = {}
    for d, ti, to_ in rows:
        if not d:
            continue
        by_day[d] = {"input": int(ti or 0), "output": int(to_ or 0)}

    days_out = []
    for i in range(7):
        d = cutoff_date + timedelta(days=i)
        key = d.isoformat()
        entry = by_day.get(key, {"input": 0, "output": 0})
        days_out.append({
            "date": key,
            "input": entry["input"],
            "output": entry["output"],
            "tokens": entry["input"] + entry["output"],
        })
    total = sum(d["tokens"] for d in days_out)
    return {"days": days_out, "total": total}


# ---------------------------------------------------------------------------
# public entrypoint
# ---------------------------------------------------------------------------


def collect_observability() -> dict[str, Any]:
    """Aggregate all observability metrics into a single response payload."""
    return {
        "translate_cache_hit_rate_24h": _translate_cache_hit_rate_24h(),
        "pipeline_step_p95_24h": _pipeline_step_p95_24h(),
        "pipeline_failure_rate_24h": _pipeline_failure_rate_24h(),
        "judge_rejection_rate_24h": _judge_rejection_rate_24h(),
        "daily_token_spend_7d": _daily_token_spend_7d(),
        "generated_at": _utcnow().isoformat(),
    }
