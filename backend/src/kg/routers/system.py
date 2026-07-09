"""System-level observability endpoint — no auth required."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends
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
async def system_info() -> SystemInfoResponse:
    version = _VERSION

    from datetime import UTC, datetime
    started_at = datetime.fromtimestamp(_STARTED_AT, tz=UTC).isoformat()
    uptime_seconds = int(time.time() - _STARTED_AT)

    migration_version = MIGRATION_NAMES[-1] if MIGRATION_NAMES else "none"

    # Piggyback threshold alerts on this frequently-polled endpoint.
    # `run_all_checks` itself swallows exceptions; the outer guard is belt-and-
    # suspenders to ensure /api/system/info never 500s for an observability bug.
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
