from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from ..domain.runtime_models import RuntimeReceipt


@runtime_checkable
class AgentRuntimePort(Protocol):
    def owner_status(self, thread_id: str) -> str: ...

    def dispatch(self, thread_id: str, instruction: str) -> None: ...


@runtime_checkable
class RuntimeReceiptPort(Protocol):
    """Read-only structured liveness source for the watchdog."""

    def runtime_receipt(self, thread_id: str) -> RuntimeReceipt | None: ...


@runtime_checkable
class RuntimeReceiptStorePort(Protocol):
    """Write-only boundary for the caller-owned liveness receipt file."""

    def write(
        self,
        receipt: RuntimeReceipt,
        *,
        expected_cycle_id: str | None = None,
        expected_last_action_id: str | None | object = None,
    ) -> RuntimeReceipt: ...

    def claim_wake(
        self,
        *,
        thread_id: str,
        wake_id: str,
        now: datetime,
        expected_cycle_id: str | None,
    ) -> RuntimeReceipt: ...
