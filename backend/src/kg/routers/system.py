"""System-level observability endpoint — no auth required."""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import observability_alerts, sentry_init
from ..deps import get_admin_user

_logger = logging.getLogger(__name__)

VERSION_FILE = Path("/app/VERSION")

# VERSION cannot change without a process restart, so read it once at import.
# NOTE: ops/kg_reconcile.sh (the push=deploy reconciler) reads this value via
# GET /api/system/info to confirm a deploy landed (reported version == target sha)
# and to cross-check the felix backend/VERSION cursor against the live container.
_VERSION: str = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "unknown"

_STARTED_AT: float = time.time()

MIGRATION_NAMES = ["root_form", "inflections"]


class SystemInfoResponse(BaseModel):
    version: str
    started_at: str
    uptime_seconds: int
    migration_version: str
    # Unauth existence-proof that the Sentry DSN was wired (deploy.md gate
    # falls back to this when /api/system/sentry-test is unavailable).
    sentry: bool


class SentryPingResponse(BaseModel):
    sent: bool
    is_active: bool
    event_id: str | None = None


router = APIRouter(tags=["system"])


@router.get("/api/system/info", response_model=SystemInfoResponse)
async def system_info(response: Response) -> SystemInfoResponse:
    response.headers["Cache-Control"] = "no-store"
    version = _VERSION

    from datetime import UTC, datetime

    started_at = datetime.fromtimestamp(_STARTED_AT, tz=UTC).isoformat()
    uptime_seconds = int(time.time() - _STARTED_AT)

    migration_version = MIGRATION_NAMES[-1] if MIGRATION_NAMES else "none"

    # Piggyback threshold alerts on this probe endpoint, throttled per process
    # (issue #2087): it is unauthenticated and rate-limit exempt, and every
    # check holds a log-DB lock the event loop also takes. The gate is entered
    # here on the event loop, so throttled requests never touch the threadpool.
    # `run_all_checks` itself swallows exceptions; the outer guard is belt-and-
    # suspenders to ensure /api/system/info never 500s for an observability bug.
    with observability_alerts.throttled_run_slot() as granted:
        if granted:
            try:
                await run_in_threadpool(observability_alerts.run_all_checks)
            except Exception:  # pragma: no cover — defensive
                _logger.warning("observability alerts run_all_checks failed", exc_info=True)

    return SystemInfoResponse(
        version=version,
        started_at=started_at,
        uptime_seconds=uptime_seconds,
        migration_version=migration_version,
        sentry=sentry_init.is_active(),
    )


# Files the process itself creates at startup (worker lock in lifespan,
# pipeline_runs.db via the orphan-run reaper). If the data dir is deleted or
# swapped under a running process they vanish, which is exactly the 2026-10-09
# failure: /api/system/info kept answering 200 while every DB-backed call 500ed.
_READY_STARTUP_FILES: tuple[tuple[str, str], ...] = (
    (".worker.lock", "worker_lock_missing"),
    ("pipeline_runs.db", "pipeline_db_missing"),
)


def readiness_failures(data_dir: Path) -> list[str]:
    """Machine-readable reasons the data dir is unusable; empty means ready.

    Only stat/open/unlink: no DB queries. Reasons never embed host paths.
    """
    if not data_dir.is_dir():
        return ["data_dir_missing"]
    reasons: list[str] = []
    if not (data_dir / "users").is_dir():
        reasons.append("users_dir_missing")
    probe = data_dir / f".ready-probe-{uuid.uuid4().hex}"
    try:
        fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except OSError:
        reasons.append("data_dir_not_writable")
    finally:
        # Also covers a failure between create and close: never leave a probe behind.
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            if "data_dir_not_writable" not in reasons:
                reasons.append("data_dir_not_writable")
    for name, reason in _READY_STARTUP_FILES:
        if not (data_dir / name).is_file():
            reasons.append(reason)
    return reasons


# The endpoint is unauthenticated and rate-limit exempt, so every hit would
# otherwise create+unlink a file. Cache the verdict briefly (per data dir).
_READY_CACHE_TTL_SECONDS = 2.0
_ready_cache: tuple[float, str, list[str]] | None = None


def _ready_clock() -> float:
    return time.monotonic()


def _reset_ready_cache() -> None:
    global _ready_cache
    _ready_cache = None


# NOTE: lives under /api/system/info/ on purpose: the rate-limit middleware
# exempts by prefix "/api/system/info", so this inherits the exemption without
# touching app_middleware. Do not move it to a sibling path without also adding
# the path to `rate_limit_exempt_prefixes` (the exemption test will fail).
@router.get("/api/system/info/ready", include_in_schema=False)
async def system_ready(request: Request) -> JSONResponse:
    """Unauthenticated fail-closed readiness: 200 only if storage is usable."""
    data_dir = Path(request.app.state.kg_settings.data_dir)
    global _ready_cache
    now = _ready_clock()
    cached = _ready_cache
    if cached is not None and cached[1] == str(data_dir) and 0 <= now - cached[0] < _READY_CACHE_TTL_SECONDS:
        reasons = list(cached[2])
    else:
        reasons = await run_in_threadpool(readiness_failures, data_dir)
        _ready_cache = (now, str(data_dir), list(reasons))
    headers = {"Cache-Control": "no-store"}
    if reasons:
        return JSONResponse({"ready": False, "reasons": reasons}, status_code=503, headers=headers)
    return JSONResponse({"ready": True}, headers=headers)


@router.get("/api/system/sentry-test", include_in_schema=False)
def sentry_test(_admin=Depends(get_admin_user)) -> dict:
    """Trigger a deliberate exception so Sentry capture can be verified end-to-end.

    Admin-only. Remove once integration is confirmed working (see Tier-1 followups).
    """
    raise RuntimeError("Sentry verification: deliberate test exception from /api/system/sentry-test")


@router.post("/api/admin/sentry/ping", include_in_schema=False, response_model=SentryPingResponse)
def sentry_admin_ping(_admin=Depends(get_admin_user)) -> SentryPingResponse:
    """Smoke-ping Sentry from the admin UI to confirm DSN wiring post-deploy.

    Unlike ``/api/system/sentry-test`` (which raises an uncaught exception so
    the Starlette integration auto-captures it), this endpoint ships a deliberate
    ``capture_message`` + a caught exception via ``capture_exception``. It never
    raises so the admin UI gets a clean JSON response with the resulting
    ``event_id`` for cross-referencing in Sentry.

    When Sentry is not initialized (no ``SENTRY_DSN``), returns
    ``{"sent": False, "is_active": False}`` — never raises.
    """
    is_active = sentry_init.is_active()
    if not is_active:
        return SentryPingResponse(sent=False, is_active=False, event_id=None)

    event_id: str | None = None
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover — sentry_sdk presence is implied by is_active()
        _logger.warning("sentry_init.is_active() True but sentry_sdk import failed")
        _logger.warning("Silently handled exception; using fallback response", exc_info=True)
        return SentryPingResponse(sent=False, is_active=True, event_id=None)

    try:
        event_id = sentry_sdk.capture_message("admin smoke ping", level="info")
        try:
            raise RuntimeError("admin smoke ping — deliberate caught exception")
        except RuntimeError as exc:
            captured = sentry_sdk.capture_exception(exc)
            # Prefer the exception event id if available; both ship to Sentry.
            event_id = captured or event_id
    except Exception:  # pragma: no cover — Sentry transport must never crash the handler
        _logger.exception("Sentry admin ping failed to dispatch")
        _logger.warning("Silently handled exception; using fallback response", exc_info=True)
        return SentryPingResponse(sent=False, is_active=True, event_id=None)

    return SentryPingResponse(sent=True, is_active=True, event_id=event_id)
