"""Threshold-based observability alerts → Sentry capture_message.

Pure read-side. Inspects pipeline_runs.db / judge_log.db / translate_log.db
and emits Sentry events when thresholds are crossed. Best-effort: failures
inside checks must never disturb the caller (typically /api/system/info).

Design notes
------------
* No background scheduler. Triggered piggyback-style from /api/system/info,
  which is hit by health probes, iOS, and the admin dashboard frequently
  enough to provide minute-resolution alerting. Trade-off: `/api/system/info`
  becomes the single point of failure for alerting — if probes stop hitting
  it (e.g. probe outage, route regression) alerts silently halt. Acceptable
  because the same endpoint is the canary used externally to detect outages.
* Per-alert in-memory cooldown (default 30 min) suppresses duplicate
  notifications within the same process. Multi-worker deployments will get
  one alert per worker per cooldown window — acceptable since Sentry
  dedupes on issue fingerprint downstream.
* Schema-readonly: queries never mutate the underlying log tables.
* Sentry tag routing: although `sentry_sdk.capture_message` in 2.x technically
  accepts `tags=` via `**scope_kwargs`, that kwarg surface is deprecated and
  slated for removal in 3.x. We attach tags through an explicit scope
  (`new_scope().set_tag()`) so behaviour is stable across SDK majors. The
  `_capture` helper is the only edge that touches Sentry and is the test seam
  used by `tests/`.

Public API
----------
check_pipeline_failures(window_min, threshold, include_interrupted=False)
check_judge_rejection_rate(window_min, min_total, threshold)
check_translate_latency_p95(window_min, threshold_ms)
run_all_checks()  — calls all three with module defaults.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from . import judge_log, pipeline_log, translate_log

_logger = logging.getLogger(__name__)

_MISSING_SENTRY = object()

# ---------------------------------------------------------------------------
# Sentry binding (rebindable for tests).
# ---------------------------------------------------------------------------

try:
    import sentry_sdk as _sentry_sdk  # type: ignore[assignment]
except ImportError:  # pragma: no cover — sentry-sdk is a declared dep
    # Distinguish "SDK import missing in this environment" from the explicit
    # None used by tests to assert the availability guard short-circuits _emit.
    _sentry_sdk = _MISSING_SENTRY  # type: ignore[assignment]


def _capture(message: str, level: str, tags: dict[str, Any]) -> None:
    """Send a Sentry message with tags routed through an explicit scope.

    This is the ONE edge that touches Sentry — tests monkeypatch this with a
    strict-signature stub. `sentry_sdk.capture_message` in 2.x technically
    forwards `tags=` via `**scope_kwargs`, but that path is deprecated and
    scheduled for removal in 3.x. `push_scope` itself is also deprecated in
    2.x in favour of `new_scope` / `isolation_scope`, so we use `new_scope`
    to stay forward-compatible: tags applied to the forked scope flow into
    the captured event and the scope is torn down on `__exit__`.
    """
    if _sentry_sdk is None or _sentry_sdk is _MISSING_SENTRY:
        return
    with _sentry_sdk.new_scope() as scope:
        for k, v in tags.items():
            scope.set_tag(k, v)
        _sentry_sdk.capture_message(message, level=level)


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
    if _sentry_sdk is None:
        return
    payload_tags = {"alert": alert_key, **tags}
    try:
        _capture(message, level, payload_tags)
    except Exception:
        _logger.warning("sentry capture_message failed", exc_info=True)
        return
    _stamp_cooldown(alert_key)


# ---------------------------------------------------------------------------
# Checks.
# ---------------------------------------------------------------------------


def _query_log(
    module: Any,
    sql: str,
    params: tuple[Any, ...],
    *,
    fetch_all: bool = False,
    error_label: str,
) -> Any:
    """Run a read-only query under the log module's lock; None on failure.

    Centralises the lock/conn/execute/except-warn skeleton shared by the
    threshold checks. Returns the cursor's fetchall() (when `fetch_all`) or
    fetchone() result, or None if the query raised — letting callers
    short-circuit exactly as the inline try/except did before.
    """
    try:
        with module._lock:
            conn = module._get_conn()
            cur = conn.execute(sql, params)
            return cur.fetchall() if fetch_all else cur.fetchone()
    except Exception:
        _logger.warning("%s check query failed", error_label, exc_info=True)
        return None


# Hard failure statuses. `interrupted` is operational (user-cancelled or
# graceful shutdown) and is excluded from alerting by default — opt in via
# `include_interrupted=True` if you want to surface those too.
_FAILURE_STATUSES: tuple[str, ...] = ("failed", "error")
_INTERRUPTED_STATUSES: tuple[str, ...] = ("interrupted",)


def check_pipeline_failures(
    *,
    window_min: int = PIPELINE_WINDOW_MIN,
    threshold: int = PIPELINE_FAILURE_THRESHOLD,
    include_interrupted: bool = False,
) -> None:
    """Emit Sentry error if pipeline failures in last `window_min` >= threshold.

    The window is framed by failure-completion time (`ended_at`), so a run that
    started before the window but failed inside it is still counted. Falls back
    to `started_at` only for orphaned rows with a NULL `ended_at`.

    `interrupted` runs are excluded from the failure count by default. Pass
    `include_interrupted=True` to fold them in (useful when operators want
    visibility into cancellations alongside hard failures).
    """
    statuses = _FAILURE_STATUSES + (
        _INTERRUPTED_STATUSES if include_interrupted else ()
    )
    cutoff = (_now() - timedelta(minutes=window_min)).isoformat()
    placeholders = ",".join("?" for _ in statuses)
    # Window by failure-occurrence time, not run start. A long-running
    # pipeline can start before the window yet fail inside it; framing
    # by `started_at` would silently drop it. `ended_at` is set by
    # `end_run` for every failed/error run; `COALESCE` falls back to
    # `started_at` only for orphaned rows with a NULL `ended_at`. This
    # mirrors the judge/translate checks, which window by `created_at`
    # (event-occurrence time).
    row = _query_log(
        pipeline_log,
        f"SELECT COUNT(*) FROM pipeline_runs "
        f"WHERE status IN ({placeholders}) "
        f"AND COALESCE(ended_at, started_at) >= ?",
        (*statuses, cutoff),
        error_label="pipeline failure",
    )
    if row is None:
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
    row = _query_log(
        judge_log,
        "SELECT COUNT(*) AS total, "
        "       SUM(CASE WHEN accepted = 0 THEN 1 ELSE 0 END) AS rejected "
        "FROM judge_log "
        "WHERE source = 'auto' AND created_at >= ? "
        f"  AND {judge_log.DEGREE_CAP_EXCLUSION_SQL}",
        (cutoff,),
        error_label="judge rejection",
    )
    if row is None:
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
    rows = _query_log(
        translate_log,
        "SELECT latency_ms FROM translate_log "
        "WHERE created_at >= ? AND latency_ms IS NOT NULL "
        "ORDER BY latency_ms ASC",
        (cutoff,),
        fetch_all=True,
        error_label="translate latency",
    )
    if rows is None:
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
