"""Shared type definitions for the KG backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict


class UserRecord(TypedDict, total=False):
    """Authenticated user context returned by resolve_current_user."""

    id: str
    dir: Path
    record: dict[str, Any]
    config: dict[str, Any]


class QuotaState(TypedDict):
    """Quota snapshot crossing the iOS API boundary: remaining fraction + reset window."""

    fraction: float
    reset_seconds: float


class QuotaCheck(TypedDict):
    """Pre-flight quota gate result crossing the iOS API boundary."""

    exceeded: bool
    fraction: float
    reset_seconds: float
