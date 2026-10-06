"""Validation evidence and check-result value objects for handback contracts."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import InvalidReceipt

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GREEN_HANDBACK_STATUSES = frozenset({"pass", "passed", "green", "ok", "success"})


class CheckStatus(StrEnum):
    ABSENT = "absent"
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"


def _has_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _require_sha(name: str, value: object) -> str:
    if type(value) is not str or not _SHA_RE.fullmatch(value):
        raise InvalidReceipt(f"{name} must be a lowercase 40-character Git SHA")
    return value


def _require_text(name: str, value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or _has_control(value)
    ):
        raise InvalidReceipt(f"{name} must be non-empty canonical text")
    return value


def _require_generation(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise InvalidReceipt(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class ValidationEvidence:
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    observed_at: datetime
    log_path: str | None = None

    def __post_init__(self) -> None:
        if type(self.command) is not tuple or not self.command:
            raise InvalidReceipt("validation command must be a non-empty tuple")
        for item in self.command:
            _require_text("validation command item", item)
        if type(self.exit_code) is not int:
            raise InvalidReceipt("validation exit_code must be an integer")
        if type(self.duration_seconds) is not float or not math.isfinite(
            self.duration_seconds
        ):
            raise InvalidReceipt("validation duration must be a finite float")
        if self.duration_seconds < 0:
            raise InvalidReceipt("validation duration cannot be negative")
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.utcoffset() is None
        ):
            raise InvalidReceipt("validation timestamp must be offset-aware")
        if self.log_path is not None:
            _require_text("validation log_path", self.log_path)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "observed_at": self.observed_at.isoformat(),
        }
        if self.log_path is not None:
            payload["log_path"] = self.log_path
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ValidationEvidence:
        try:
            command = payload["command"]
            exit_code = payload["exit_code"]
            duration = payload["duration_seconds"]
            observed_at = payload["observed_at"]
            log_path = payload.get("log_path")
            if not isinstance(command, list) or any(
                type(item) is not str for item in command
            ):
                raise TypeError("command must be a list of strings")
            if type(exit_code) is not int:
                raise TypeError("exit_code must be an integer")
            if type(duration) is not float:
                raise TypeError("duration_seconds must be a float")
            if type(observed_at) is not str:
                raise TypeError("observed_at must be a string")
            if log_path is not None and type(log_path) is not str:
                raise TypeError("log_path must be a string")
            return cls(
                command=tuple(command),
                exit_code=exit_code,
                duration_seconds=duration,
                observed_at=datetime.fromisoformat(observed_at),
                log_path=log_path,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidReceipt("validation evidence is malformed") from error


@dataclass(frozen=True)
class HandbackOutcome:
    """Lossless canonical form of one registry handback outcome object."""

    canonical_json: str

    def __post_init__(self) -> None:
        try:
            payload = json.loads(self.canonical_json)
            if not isinstance(payload, dict):
                raise TypeError("handback outcome must be an object")
            status = payload.get("status")
            if (
                type(status) is not str
                or status.strip().lower() not in _GREEN_HANDBACK_STATUSES
            ):
                raise TypeError("handback outcome status must be green")
            canonical = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise InvalidReceipt("handback outcome is malformed") from error
        if canonical != self.canonical_json:
            raise InvalidReceipt("handback outcome must be canonical JSON")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> HandbackOutcome:
        if not isinstance(payload, Mapping):
            raise InvalidReceipt("handback outcome must be an object")
        try:
            canonical = json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise InvalidReceipt("handback outcome is malformed") from error
        return cls(canonical_json=canonical)

    def to_payload(self) -> dict[str, Any]:
        payload = json.loads(self.canonical_json)
        if not isinstance(payload, dict):  # pragma: no cover - guarded at construction
            raise InvalidReceipt("handback outcome is malformed")
        return payload
