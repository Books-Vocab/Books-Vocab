"""System-level observability endpoint — no auth required."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import observability_alerts
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
