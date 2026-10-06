"""Unified recent-activity timeline for the admin user-detail page.

Merges three SQLite sources — ``translate_log``, ``pipeline_runs``, ``judge_log`` —
within a bounded time window. Each row is normalised into a small event dict
sortable by ``created_at`` (ISO 8601 UTC) so the UI can render a single feed.

This module reads only; it never writes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

MAX_HOURS = 168  # 7 days — keeps per-source LIMIT bounded.
MAX_PER_SOURCE = 500
MAX_TOTAL_EVENTS = 500
_SOURCE_PRECEDENCE = {"judge": 0, "pipeline": 1, "translate": 2}
_MIN_UTC = datetime.min.replace(tzinfo=UTC)


def _clamp_hours(hours: int) -> int:
    try:
        h = int(hours)
    except (TypeError, ValueError):
        logger.warning("Invalid hours input %r in activity query; using fallback 24", hours)
        h = 24
    if h < 1:
        return 1
    if h > MAX_HOURS:
        return MAX_HOURS
    return h


def _utc_instant(value: str | None) -> datetime | None:
    """Parse an ISO timestamp as a comparable UTC instant."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_cutoff_params(since_iso: str) -> tuple[str, str]:
    """Return a conservative indexed date bound plus the exact cutoff."""
    cutoff = _utc_instant(since_iso)
    if cutoff is None:
        return since_iso, since_iso
    return (cutoff.date() - timedelta(days=1)).isoformat(), since_iso


def _utc_instant_predicate(column: str) -> str:
    """Build an SQLite predicate that filters ISO timestamps by UTC instant."""
    return f"{column} >= ? AND julianday({column}) >= julianday(?)"


def _translate_events(user_id: str, since_iso: str) -> list[dict[str, Any]]:
    import kg.translate_log as tl

    candidate_bound, exact_cutoff = _utc_cutoff_params(since_iso)
    with tl._lock:
        conn = tl._get_conn()
        rows = conn.execute(
            "SELECT id, operation, word, context, latency_ms, created_at"
            " FROM translate_log WHERE user_id = ? AND "
            f"{_utc_instant_predicate('created_at')}"
            " ORDER BY julianday(created_at) DESC, id DESC LIMIT ?",
            (user_id, candidate_bound, exact_cutoff, MAX_PER_SOURCE),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "type": "translate",
                "id": row[0],
                "operation": row[1],
                "word": row[2],
                "context": row[3],
                "latency_ms": row[4],
                "created_at": row[5],
            }
        )
    return out


def _pipeline_events(user_id: str, since_iso: str) -> list[dict[str, Any]]:
    import kg.pipeline_log as pl

    candidate_bound, exact_cutoff = _utc_cutoff_params(since_iso)
    with pl._lock:
        conn = pl._get_conn()
        rows = conn.execute(
            "SELECT id, run_id, notebook_id, trigger, started_at, ended_at, status"
            " FROM pipeline_runs WHERE user_id = ? AND "
            f"{_utc_instant_predicate('started_at')}"
            " ORDER BY julianday(started_at) DESC, id DESC LIMIT ?",
            (user_id, candidate_bound, exact_cutoff, MAX_PER_SOURCE),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for source_id, run_id, nb, trigger, started, ended, status in rows:
        duration_s: float | None = None
        if started and ended:
            try:
                duration_s = round(
                    (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds(),
                    2,
                )
            except (ValueError, TypeError):
                logger.debug(
                    "Failed parsing pipeline event timestamps for user=%s run_id=%s started=%r ended=%r",
                    user_id,
                    run_id,
                    started,
                    ended,
                )
                duration_s = None
        out.append(
            {
                "type": "pipeline",
                "run_id": run_id,
                "notebook_id": nb,
                "trigger": trigger,
                "status": status,
                "duration_s": duration_s,
                "ended_at": ended,
                "created_at": started,
                "_source_id": source_id,
            }
        )
    return out


def _judge_events(user_id: str, since_iso: str) -> list[dict[str, Any]]:
    import kg.judge_log as jl

    candidate_bound, exact_cutoff = _utc_cutoff_params(since_iso)
    with jl._lock:
        conn = jl._get_conn()
        rows = conn.execute(
            "SELECT id, notebook_id, from_id, to_id, similarity, verdict,"
            " confidence, accepted, source, created_at"
            " FROM judge_log WHERE user_id = ? AND "
            f"{_utc_instant_predicate('created_at')}"
            " ORDER BY julianday(created_at) DESC, id DESC LIMIT ?",
            (user_id, candidate_bound, exact_cutoff, MAX_PER_SOURCE),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "type": "judge",
                "id": row[0],
                "notebook_id": row[1],
                "from_id": row[2],
                "to_id": row[3],
                "similarity": row[4],
                "verdict": row[5],
                "confidence": row[6],
                "accepted": jl._accepted_from_storage(row[7]),
                "source": row[8],
                "created_at": row[9],
            }
        )
    return out


def get_user_activity(user_id: str, *, hours: int = 24) -> dict[str, Any]:
    """Return merged recent activity for a user, newest first.

    Returns:
        ``{"user_id", "hours", "since", "events", "counts", "truncated"}``.
        ``counts`` maps source name → row count *post-window*, itself capped
        at ``MAX_PER_SOURCE`` (the per-source query LIMIT). ``truncated`` maps
        source name → bool: ``True`` when that source hit the cap, signalling
        ``counts`` for it is a **lower bound**, not the exact total. ``events``
        is capped at ``MAX_TOTAL_EVENTS``.
    """
    hours = _clamp_hours(hours)
    since_dt = datetime.now(UTC) - timedelta(hours=hours)
    since_iso = since_dt.isoformat()

    translate = _translate_events(user_id, since_iso)
    pipeline = _pipeline_events(user_id, since_iso)
    judge = _judge_events(user_id, since_iso)

    counts = {
        "translate": len(translate),
        "pipeline": len(pipeline),
        "judge": len(judge),
    }
    # A source whose row count equals the per-source LIMIT was truncated:
    # ``counts`` for it is a lower bound, not the true total.
    truncated = {name: n >= MAX_PER_SOURCE for name, n in counts.items()}

    all_events = translate + pipeline + judge
    all_events.sort(
        key=lambda event: (
            _utc_instant(event.get("created_at")) or _MIN_UTC,
            _SOURCE_PRECEDENCE[event["type"]],
            event.get("_source_id", event.get("id", -1)),
        ),
        reverse=True,
    )
    if len(all_events) > MAX_TOTAL_EVENTS:
        all_events = all_events[:MAX_TOTAL_EVENTS]
    for event in all_events:
        event.pop("_source_id", None)

    return {
        "user_id": user_id,
        "hours": hours,
        "since": since_iso,
        "events": all_events,
        "counts": counts,
        "truncated": truncated,
    }
