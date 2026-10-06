"""Immutable duration-only operational telemetry values."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .errors import DeliveryContractError

TELEMETRY_SCHEMA = "kg.delivery.telemetry.duration.v1"
TELEMETRY_WARNING_SCHEMA = "kg.delivery.telemetry.warning.v1"


class InvalidTelemetry(DeliveryContractError):
    """Raised when a duration sample is malformed or ambiguous."""


class TelemetryMetric(StrEnum):
    HANDBACK_TO_PR = "handback_to_pr"
    PR_TO_REQUIRED_START = "pr_to_required_start"
    REQUIRED_DURATION = "required_duration"
    REQUIRED_SUCCESS_TO_ENQUEUE = "required_success_to_enqueue"
    MERGE_TO_SYNC = "merge_to_sync"
    MERGE_TO_CLEANUP = "merge_to_cleanup"


def sample_key_for(metric: TelemetryMetric, subject: str) -> str:
    normalized = TelemetryMetric(metric)
    if type(subject) is not str or not subject:
        raise InvalidTelemetry("telemetry subject must be canonical text")
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
    return f"{normalized.value}:{digest}"


def canonical_subject(**parts: str | int) -> str:
    """Encode exact subject identity without introducing lifecycle state."""

    if not parts:
        raise InvalidTelemetry("telemetry subject must not be empty")
    for name, value in parts.items():
        if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise InvalidTelemetry("telemetry subject field is not canonical")
        if type(value) not in {str, int} or value == "":
            raise InvalidTelemetry(f"telemetry subject {name} is not canonical")
        if isinstance(value, str) and any(
            ord(char) < 32 or ord(char) == 127 for char in value
        ):
            raise InvalidTelemetry(f"telemetry subject {name} is not canonical")
    return json.dumps(parts, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def publication_subject(
    *, lane_id: str, claim_generation: int, head_sha: str, pr_number: int
) -> str:
    return canonical_subject(
        lane=lane_id,
        generation=claim_generation,
        head=head_sha,
        pr=pr_number,
    )


def pull_request_subject(*, pr_number: int, head_sha: str) -> str:
    return canonical_subject(pr=pr_number, head=head_sha)


def queue_subject(*, pr_number: int, head_sha: str, queue_entry_id: str) -> str:
    return canonical_subject(
        pr=pr_number,
        head=head_sha,
        queue_entry=queue_entry_id,
    )


def main_subject(*, origin_main_sha: str) -> str:
    return canonical_subject(origin_main=origin_main_sha)


@dataclass(frozen=True)
class DurationSample:
    metric: TelemetryMetric
    subject: str
    started_at: datetime
    completed_at: datetime
    schema: str = field(default=TELEMETRY_SCHEMA, init=False)

    def __post_init__(self) -> None:
        try:
            metric = TelemetryMetric(self.metric)
        except (TypeError, ValueError) as error:
            raise InvalidTelemetry(
                f"unsupported telemetry metric: {self.metric!r}"
            ) from error
        object.__setattr__(self, "metric", metric)
        if (
            type(self.subject) is not str
            or not self.subject
            or any(ord(char) < 32 or ord(char) == 127 for char in self.subject)
        ):
            raise InvalidTelemetry("telemetry subject must be canonical text")
        for name in ("started_at", "completed_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise InvalidTelemetry(f"telemetry {name} must be offset-aware")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.completed_at < self.started_at:
            raise InvalidTelemetry("telemetry duration cannot be negative")

    @property
    def sample_key(self) -> str:
        return sample_key_for(self.metric, self.subject)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "sample_key": self.sample_key,
            "metric": self.metric.value,
            "subject": self.subject,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> DurationSample:
        if not isinstance(payload, Mapping):
            raise InvalidTelemetry("telemetry payload must be an object")
        try:
            if payload.get("schema") != TELEMETRY_SCHEMA:
                raise InvalidTelemetry(f"telemetry schema must be {TELEMETRY_SCHEMA}")
            metric = payload["metric"]
            subject = payload["subject"]
            sample_key = payload["sample_key"]
            started_at = payload["started_at"]
            completed_at = payload["completed_at"]
            duration = payload["duration_seconds"]
            if not all(
                type(value) is str
                for value in (metric, subject, sample_key, started_at, completed_at)
            ):
                raise InvalidTelemetry("telemetry payload has malformed text fields")
            if type(duration) not in {int, float} or not math.isfinite(float(duration)):
                raise InvalidTelemetry("telemetry duration must be finite")
            sample = cls(
                metric=TelemetryMetric(metric),
                subject=subject,
                started_at=datetime.fromisoformat(started_at),
                completed_at=datetime.fromisoformat(completed_at),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, InvalidTelemetry):
                raise
            raise InvalidTelemetry("telemetry payload is malformed") from error
        if sample.sample_key != sample_key:
            raise InvalidTelemetry("telemetry sample_key does not match subject")
        if not math.isclose(
            sample.duration_seconds, float(duration), rel_tol=0.0, abs_tol=1e-6
        ):
            raise InvalidTelemetry("telemetry duration does not match timestamps")
        return sample


@dataclass(frozen=True)
class TelemetryProblem:
    identity: str
    reason: str
    source: str = "telemetry"


@dataclass(frozen=True)
class TelemetryReadResult:
    samples: tuple[DurationSample, ...]
    problems: tuple[TelemetryProblem, ...] = ()


@dataclass(frozen=True)
class TelemetryWarning:
    code: str
    message: str
    metric: TelemetryMetric | None = None
    sample_key: str | None = None
    schema: str = field(default=TELEMETRY_WARNING_SCHEMA, init=False)
