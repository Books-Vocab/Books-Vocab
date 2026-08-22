"""Locked append-only NDJSON adapter for duration telemetry."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from ..domain.errors import CompareAndSwapConflict, DeliverySourceError
from ..domain.telemetry import (
    DurationSample,
    InvalidTelemetry,
    TelemetryProblem,
    TelemetryReadResult,
)


class TelemetryNdjsonAdapter:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    @staticmethod
    def _decode_lines(
        lines: list[str],
    ) -> tuple[dict[str, DurationSample], list[TelemetryProblem]]:
        samples: dict[str, DurationSample] = {}
        problems: list[TelemetryProblem] = []
        for line_number, raw in enumerate(lines, start=1):
            if not raw.strip():
                problems.append(
                    TelemetryProblem(f"line:{line_number}", "blank journal row")
                )
                continue
            try:
                payload = json.loads(raw)
                if not isinstance(payload, Mapping):
                    raise InvalidTelemetry("telemetry row must be an object")
                sample = DurationSample.from_payload(payload)
            except (json.JSONDecodeError, InvalidTelemetry) as error:
                problems.append(TelemetryProblem(f"line:{line_number}", str(error)))
                continue
            existing = samples.get(sample.sample_key)
            if existing is not None and existing != sample:
                problems.append(
                    TelemetryProblem(
                        sample.sample_key,
                        "conflicting duplicate telemetry sample_key",
                    )
                )
                continue
            samples[sample.sample_key] = sample
        return samples, problems

    def append(self, sample: DurationSample) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stream.seek(0)
                samples, problems = self._decode_lines(stream.readlines())
                if problems:
                    first = problems[0]
                    raise DeliverySourceError(
                        f"telemetry journal malformed at {first.identity}: {first.reason}"
                    )
                existing = samples.get(sample.sample_key)
                if existing == sample:
                    return False
                if existing is not None:
                    raise CompareAndSwapConflict(
                        f"telemetry sample_key conflict: {sample.sample_key}"
                    )
                stream.seek(0, os.SEEK_END)
                stream.write(
                    json.dumps(
                        sample.to_payload(),
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
                return True
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def read_since(self, since: datetime) -> TelemetryReadResult:
        if since.utcoffset() is None:
            raise ValueError("telemetry read boundary must be offset-aware")
        if not self.path.exists():
            return TelemetryReadResult(())
        with self.path.open("r", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            try:
                samples, problems = self._decode_lines(stream.readlines())
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        selected = tuple(
            sorted(
                (sample for sample in samples.values() if sample.completed_at >= since),
                key=lambda item: (item.completed_at, item.sample_key),
            )
        )
        return TelemetryReadResult(selected, tuple(problems))
