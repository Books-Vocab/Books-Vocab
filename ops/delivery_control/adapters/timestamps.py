"""Strict parsing for optional timestamps returned by external adapters."""

from __future__ import annotations

from datetime import datetime

from .errors import AdapterPayloadError


def parse_optional_timestamp(value: object, *, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    if type(value) is not str:
        raise AdapterPayloadError(f"{field} timestamp is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdapterPayloadError(f"{field} timestamp is invalid") from error
    if parsed.utcoffset() is None:
        raise AdapterPayloadError(f"{field} timestamp is not offset-aware")
    return parsed
