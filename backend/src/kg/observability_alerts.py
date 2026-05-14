"""Threshold-based observability alerts → Sentry capture_message.

Pure read-side. Inspects pipeline_runs.db / judge_log.db / translate_log.db
and emits Sentry events when thresholds are crossed. Best-effort: failures
inside checks must never disturb the caller (typically /api/system/info).

Design notes
------------
* No background scheduler. Triggered piggyback-style from /api/system/info,
  which is hit by health probes, iOS, and the admin dashboard frequently
  enough to provide minute-resolution alerting.
* Per-alert in-memory cooldown (default 30 min) suppresses duplicate
  notifications within the same process. Multi-worker deployments will get
  one alert per worker per cooldown window — acceptable since Sentry
  dedupes on issue fingerprint downstream.
* Schema-readonly: queries never mutate the underlying log tables.

Public API
----------
check_pipeline_failures(window_min, threshold)
check_judge_rejection_rate(window_min, min_total, threshold)
check_translate_latency_p95(window_min, threshold_ms)
run_all_checks()  — calls all three with module defaults.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from . import judge_log, pipeline_log, translate_log

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentry binding (rebindable for tests).
# ---------------------------------------------------------------------------

_capture_message: Callable[..., Any] | None
try:
    import sentry_sdk

    _capture_message = sentry_sdk.capture_message  # type: ignore[assignment]
except ImportError:  # pragma: no cover — sentry-sdk is a declared dep
    _capture_message = None


# ---------------------------------------------------------------------------
# Cooldown state.
# ---------------------------------------------------------------------------

COOLDOWN_MIN = 30
PIPELINE_FAILURE_THRESHOLD = 5
PIPELINE_WINDOW_MIN = 60
JUDGE_WINDOW_MIN = 60
JUDGE_MIN_TOTAL = 10
JUDGE_REJECT_THRESHOLD = 0.5
TRANSLATE_WINDOW_MIN = 15
TRANSLATE_P95_THRESHOLD_MS = 5000

# Maps alert key → datetime of last emission. Test fixture clears.
_cooldown_state: dict[str, datetime] = {}


def _now() -> datetime:
    """Indirection so tests can monkeypatch the wall clock."""
    return datetime.now(UTC)


def _within_cooldown(alert_key: str) -> bool:
    last = _cooldown_state.get(alert_key)
    if last is None:
        return False
    return (_now() - last) < timedelta(minutes=COOLDOWN_MIN)


def _stamp_cooldown(alert_key: str) -> None:
    _cooldown_state[alert_key] = _now()


def _emit(*, alert_key: str, level: str, message: str, tags: dict[str, Any]) -> None:
    """Send Sentry capture_message respecting cooldown + availability."""
    if _within_cooldown(alert_key):
        return
    capture = _capture_message
    if capture is None:
        return
    payload_tags = {"alert": alert_key, **tags}
    try:
        capture(message, level=level, tags=payload_tags)
    except Exception:
        _logger.warning("sentry capture_message failed", exc_info=True)
        return
    _stamp_cooldown(alert_key)


# ---------------------------------------------------------------------------
# Checks.
# ---------------------------------------------------------------------------


_FAILURE_STATUSES = ("failed", "error", "interrupted")


def check_pipeline_failures(
    *,
    window_min: int = PIPELINE_WINDOW_MIN,
    threshold: int = PIPELINE_FAILURE_THRESHOLD,
) -> None:
    """Emit Sentry error if pipeline failures in last `window_min` >= threshold."""
    cutoff = (_now() - timedelta(minutes=window_min)).isoformat()
    placeholders = ",".join("?" for _ in _FAILURE_STATUSES)
    try:
        conn = pipeline_log._get_conn()
        with pipeline_log._lock:
            row = conn.execute(
                f"SELECT COUNT(*) FROM pipeline_runs "
                f"WHERE status IN ({placeholders}) AND started_at >= ?",
                (*_FAILURE_STATUSES, cutoff),
            ).fetchone()
    except Exception:
        _logger.warning("pipeline failure check query failed", exc_info=True)
        return
    count = int(row[0] or 0)
    if count < threshold:
        return
    _emit(
        alert_key="pipeline_failures",
        level="error",
        message=(
            f"Pipeline failures spiked: {count} failed runs in last "
            f"{window_min}m (threshold {threshold})"
        ),
        tags={
            "pipeline_failures": count,
            "window_min": window_min,
            "threshold": threshold,
        },
    )


def check_judge_rejection_rate(
    *,
    window_min: int = JUDGE_WINDOW_MIN,
    min_total: int = JUDGE_MIN_TOTAL,
    threshold: float = JUDGE_REJECT_THRESHOLD,
) -> None:
    """Emit Sentry warning if rejection rate > threshold and sample >= min_total."""
    cutoff = (_now() - timedelta(minutes=window_min)).isoformat()
    try:
        conn = judge_log._get_conn()
        with judge_log._lock:
            row = conn.execute(
                "SELECT COUNT(*) AS total, "
                "       SUM(CASE WHEN accepted = 0 THEN 1 ELSE 0 END) AS rejected "
                "FROM judge_log "
                "WHERE source = 'auto' AND created_at >= ?",
                (cutoff,),
            ).fetchone()
    except Exception:
        _logger.warning("judge rejection check query failed", exc_info=True)
        return
    total = int(row[0] or 0)
    rejected = int(row[1] or 0)
    if total < min_total:
        return
    rate = rejected / total
    if rate <= threshold:
        return
    _emit(
        alert_key="judge_rejection_rate",
        level="warning",
        message=(
            f"Judge rejection rate elevated: {rejected}/{total} = "
            f"{rate:.2%} in last {window_min}m (threshold {threshold:.0%})"
        ),
        tags={
            "total": total,
            "rejected": rejected,
            "rejection_rate": round(rate, 4),
            "window_min": window_min,
            "threshold": threshold,
        },
    )


def check_translate_latency_p95(
    *,
    window_min: int = TRANSLATE_WINDOW_MIN,
    threshold_ms: int = TRANSLATE_P95_THRESHOLD_MS,
    min_samples: int = 10,
) -> None:
    """Emit Sentry warning if p95 translate latency > threshold_ms.

    Skips when sample size in the window is below `min_samples` — small samples
    yield unstable p95 numbers and create noise.
    """
    cutoff = (_now() - timedelta(minutes=window_min)).isoformat()
    try:
        conn = translate_log._get_conn()
        with translate_log._lock:
            rows = conn.execute(
                "SELECT latency_ms FROM translate_log "
                "WHERE created_at >= ? AND latency_ms IS NOT NULL "
                "ORDER BY latency_ms ASC",
                (cutoff,),
            ).fetchall()
    except Exception:
        _logger.warning("translate latency check query failed", exc_info=True)
        return

    samples = [int(r[0]) for r in rows if r[0] is not None]
    if len(samples) < min_samples:
        return

    # Inclusive p95 — index = ceil(0.95 * n) - 1.
    n = len(samples)
    idx = max(0, min(n - 1, int(0.95 * n + 0.9999999) - 1))
    p95 = samples[idx]
    if p95 <= threshold_ms:
        return
    _emit(
        alert_key="translate_latency_p95",
        level="warning",
        message=(
            f"Translate latency p95 spiked: {p95}ms in last "
            f"{window_min}m (threshold {threshold_ms}ms, n={n})"
        ),
        tags={
            "p95_ms": p95,
            "samples": n,
            "window_min": window_min,
            "threshold_ms": threshold_ms,
        },
    )


# ---------------------------------------------------------------------------
# Composite runner.
# ---------------------------------------------------------------------------


def run_all_checks() -> None:
    """Run every threshold check, swallowing per-check exceptions.

    Designed for fire-and-forget invocation from /api/system/info. Never
    raises; the only side effect is a Sentry event (or a logger.warning).
    """
    for fn in (
        check_pipeline_failures,
        check_judge_rejection_rate,
        check_translate_latency_p95,
    ):
        try:
            fn()
        except Exception:
            _logger.warning("observability check %s failed", fn.__name__, exc_info=True)
