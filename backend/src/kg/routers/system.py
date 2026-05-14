"""System-level observability endpoint — no auth required."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import observability_alerts, sentry_init
from ..deps import get_admin_user

_logger = logging.getLogger(__name__)

VERSION_FILE = Path("/app/VERSION")

_STARTED_AT: float = time.time()

MIGRATION_NAMES = ["root_form", "inflections"]


class SystemInfoResponse(BaseModel):
    version: str
    started_at: str
    uptime_seconds: int
    migration_version: str


router = APIRouter()


@router.get("/api/system/info", response_model=SystemInfoResponse)
def system_info() -> SystemInfoResponse:
    version = "unknown"
    if VERSION_FILE.exists():
        version = VERSION_FILE.read_text().strip()

    from datetime import datetime, UTC
    started_at = datetime.fromtimestamp(_STARTED_AT, tz=UTC).isoformat()
    uptime_seconds = int(time.time() - _STARTED_AT)

    migration_version = MIGRATION_NAMES[-1] if MIGRATION_NAMES else "none"

    # Piggyback threshold alerts on this frequently-polled endpoint.
    # `run_all_checks` itself swallows exceptions; the outer guard is belt-and-
    # suspenders to ensure /api/system/info never 500s for an observability bug.
    try:
        observability_alerts.run_all_checks()
    except Exception:  # pragma: no cover — defensive
        _logger.warning("observability alerts run_all_checks failed", exc_info=True)

    return SystemInfoResponse(
        version=version,
        started_at=started_at,
        uptime_seconds=uptime_seconds,
        migration_version=migration_version,
    )


@router.get("/api/system/sentry-test", include_in_schema=False)
def sentry_test(_admin=Depends(get_admin_user)) -> dict:
    """Trigger a deliberate exception so Sentry capture can be verified end-to-end.

    Admin-only. Remove once integration is confirmed working (see Tier-1 followups).
    """
    raise RuntimeError("Sentry verification: deliberate test exception from /api/system/sentry-test")


@router.post("/api/admin/sentry/ping", include_in_schema=False)
def sentry_admin_ping(_admin=Depends(get_admin_user)) -> dict[str, Any]:
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
        return {"sent": False, "is_active": False, "event_id": None}

    event_id: str | None = None
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover — sentry_sdk presence is implied by is_active()
        _logger.warning("sentry_init.is_active() True but sentry_sdk import failed")
        return {"sent": False, "is_active": True, "event_id": None}

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
        return {"sent": False, "is_active": True, "event_id": None}

    return {"sent": True, "is_active": True, "event_id": event_id}
