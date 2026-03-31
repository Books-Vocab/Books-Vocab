"""System-level observability endpoint — no auth required."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

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

    return SystemInfoResponse(
        version=version,
        started_at=started_at,
        uptime_seconds=uptime_seconds,
        migration_version=migration_version,
    )
