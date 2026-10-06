"""Non-blocking recording and read-only rolling telemetry queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..domain.telemetry import (
    DurationSample,
    TelemetryMetric,
    TelemetryProblem,
    TelemetryReadResult,
    TelemetryWarning,
)
from ..ports.telemetry import TelemetryStorePort


class TelemetryService:
    def __init__(self, store: TelemetryStorePort) -> None:
        self.store = store

    def record(
        self,
        *,
        metric: TelemetryMetric,
        subject: str,
        started_at: datetime | None,
        completed_at: datetime | None,
    ) -> TelemetryWarning | None:
        if started_at is None or completed_at is None:
            return TelemetryWarning(
                code="telemetry_source_missing",
                message="trusted timing boundary is unavailable; sample not recorded",
                metric=metric,
            )
        sample: DurationSample | None = None
        try:
            sample = DurationSample(metric, subject, started_at, completed_at)
            self.store.append(sample)
        except (OSError, RuntimeError, ValueError) as error:
            return TelemetryWarning(
                code="telemetry_append_failed",
                message=str(error),
                metric=metric,
                sample_key=sample.sample_key if sample is not None else None,
            )
        return None

    def read_window(
        self,
        *,
        now: datetime,
        window: timedelta = timedelta(hours=1),
    ) -> TelemetryReadResult:
        if now.utcoffset() is None or window.total_seconds() <= 0:
            raise ValueError(
                "telemetry window requires aware now and positive duration"
            )
        try:
            result = self.store.read_since(now - window)
        except (OSError, RuntimeError, ValueError) as error:
            return TelemetryReadResult(
                (),
                (TelemetryProblem("journal", f"telemetry read failed: {error}"),),
            )
        future = tuple(sample for sample in result.samples if sample.completed_at > now)
        problems = result.problems + tuple(
            TelemetryProblem(sample.sample_key, "sample completion is in the future")
            for sample in future
        )
        return TelemetryReadResult(
            tuple(sample for sample in result.samples if sample.completed_at <= now),
            problems,
        )

    def find(
        self,
        *,
        sample_key: str,
        now: datetime,
        window: timedelta = timedelta(hours=1),
    ) -> tuple[DurationSample | None, tuple[TelemetryProblem, ...]]:
        result = self.read_window(now=now, window=window)
        matches = tuple(
            sample for sample in result.samples if sample.sample_key == sample_key
        )
        return (matches[0] if len(matches) == 1 else None, result.problems)
