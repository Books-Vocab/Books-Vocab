"""Typed runtime liveness facts and deterministic watchdog decisions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from .errors import InvalidReceipt
from .validation_models import _require_text

RUNTIME_SCHEMA = "kg.delivery.runtime.v1"


class RuntimeState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    FROZEN = "frozen"
    ARCHIVED = "archived"


class WatchdogAction(StrEnum):
    NOOP = "noop"
    WAKE = "wake"
    ESCALATE = "escalate"


def _require_timestamp(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidReceipt(f"{name} must be offset-aware")
    return value


def _optional_timestamp(name: str, value: object) -> datetime | None:
    if value is None:
        return None
    return _require_timestamp(name, value)


@dataclass(frozen=True)
class RuntimeReceipt:
    """One liveness receipt for one long-lived runtime role."""

    thread_id: str
    state: RuntimeState
    last_progress_at: datetime
    observed_at: datetime
    lease_until: datetime | None = None
    expected_next_event_at: datetime | None = None
    cycle_id: str | None = None
    last_action_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("runtime thread_id", self.thread_id)
        object.__setattr__(self, "state", RuntimeState(self.state))
        _require_timestamp("runtime last_progress_at", self.last_progress_at)
        _require_timestamp("runtime observed_at", self.observed_at)
        _optional_timestamp("runtime lease_until", self.lease_until)
        _optional_timestamp(
            "runtime expected_next_event_at", self.expected_next_event_at
        )
        for name in ("cycle_id", "last_action_id"):
            value = getattr(self, name)
            if value is not None:
                _require_text(f"runtime {name}", value)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RuntimeReceipt:
        if payload.get("schema") != RUNTIME_SCHEMA:
            raise InvalidReceipt("runtime receipt schema is unsupported")
        try:
            thread_id = payload["thread_id"]
            state = payload["state"]
            last_progress_at = payload["last_progress_at"]
            observed_at = payload["observed_at"]
            lease_until = payload.get("lease_until")
            expected_next_event_at = payload.get("expected_next_event_at")
            cycle_id = payload.get("cycle_id")
            last_action_id = payload.get("last_action_id")
            if type(thread_id) is not str or type(state) is not str:
                raise TypeError("thread_id and state must be strings")
            timestamp_values = {
                "last_progress_at": last_progress_at,
                "observed_at": observed_at,
                "lease_until": lease_until,
                "expected_next_event_at": expected_next_event_at,
            }
            parsed_timestamps = {
                name: (
                    None
                    if value is None
                    else datetime.fromisoformat(value)
                )
                for name, value in timestamp_values.items()
                if value is not None
            }
            if any(type(value) is not str for value in timestamp_values.values() if value is not None):
                raise TypeError("runtime timestamps must be strings")
            return cls(
                thread_id=thread_id,
                state=RuntimeState(state),
                last_progress_at=parsed_timestamps["last_progress_at"],
                observed_at=parsed_timestamps["observed_at"],
                lease_until=parsed_timestamps.get("lease_until"),
                expected_next_event_at=parsed_timestamps.get(
                    "expected_next_event_at"
                ),
                cycle_id=cycle_id,
                last_action_id=last_action_id,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidReceipt("runtime receipt payload is malformed") from error

    def to_payload(self) -> dict[str, object]:
        def timestamp(value: datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        return {
            "schema": RUNTIME_SCHEMA,
            "thread_id": self.thread_id,
            "state": self.state.value,
            "last_progress_at": self.last_progress_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "lease_until": timestamp(self.lease_until),
            "expected_next_event_at": timestamp(self.expected_next_event_at),
            "cycle_id": self.cycle_id,
            "last_action_id": self.last_action_id,
        }


@dataclass(frozen=True)
class WatchdogDecision:
    action: WatchdogAction
    reason: str
    checked_at: datetime
    wake_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", WatchdogAction(self.action))
        _require_text("watchdog reason", self.reason)
        _require_timestamp("watchdog checked_at", self.checked_at)
        if self.wake_id is not None:
            _require_text("watchdog wake_id", self.wake_id)


def _wake_id(receipt: RuntimeReceipt, *, reason: str) -> str:
    material = "|".join(
        (
            receipt.thread_id,
            receipt.cycle_id or "",
            receipt.last_progress_at.isoformat(),
            reason,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def decide_watchdog(
    receipt: RuntimeReceipt | None,
    *,
    now: datetime,
    stale_after: timedelta = timedelta(minutes=10),
) -> WatchdogDecision:
    """Return one idempotent wake decision; never dispatch an agent."""

    _require_timestamp("watchdog now", now)
    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be positive")
    if receipt is None:
        return WatchdogDecision(
            WatchdogAction.ESCALATE,
            "runtime receipt is missing",
            now,
        )
    if receipt.state in {RuntimeState.FROZEN, RuntimeState.ARCHIVED}:
        return WatchdogDecision(
            WatchdogAction.NOOP,
            f"runtime is {receipt.state.value}",
            now,
        )
    if receipt.lease_until is not None and receipt.lease_until > now:
        return WatchdogDecision(WatchdogAction.NOOP, "lease is valid", now)
    if (
        receipt.state is RuntimeState.WAITING
        and receipt.expected_next_event_at is not None
        and receipt.expected_next_event_at > now
    ):
        return WatchdogDecision(WatchdogAction.NOOP, "waiting for expected event", now)

    lease_expired = receipt.lease_until is not None and receipt.lease_until <= now
    stale = now - receipt.last_progress_at >= stale_after
    if lease_expired or stale:
        reason = "lease expired" if lease_expired else "progress is stale"
        return WatchdogDecision(
            WatchdogAction.WAKE,
            reason,
            now,
            _wake_id(receipt, reason=reason),
        )
    return WatchdogDecision(WatchdogAction.NOOP, "runtime is healthy", now)


__all__ = [
    "RUNTIME_SCHEMA",
    "RuntimeReceipt",
    "RuntimeState",
    "WatchdogAction",
    "WatchdogDecision",
    "decide_watchdog",
]
