"""Pure runtime watchdog policy used by the external Codex scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..domain.runtime_models import RuntimeReceipt, WatchdogDecision, decide_watchdog


def evaluate_runtime_watchdog(
    receipt: RuntimeReceipt | None,
    *,
    now: datetime,
    stale_after_seconds: int = 300,
) -> WatchdogDecision:
    """Evaluate liveness without sending a message or mutating any queue."""

    if type(stale_after_seconds) is not int or stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be a positive integer")
    return decide_watchdog(
        receipt,
        now=now,
        stale_after=timedelta(seconds=stale_after_seconds),
    )


__all__ = ["evaluate_runtime_watchdog"]
