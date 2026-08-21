"""Port for append-only duration telemetry."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from ..domain.telemetry import DurationSample, TelemetryReadResult


@runtime_checkable
class TelemetryStorePort(Protocol):
    def append(self, sample: DurationSample) -> bool:
        """Append once; return False for an exact replay."""

    def read_since(self, since: datetime) -> TelemetryReadResult: ...
