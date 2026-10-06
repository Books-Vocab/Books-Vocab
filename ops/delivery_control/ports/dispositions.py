"""Port for append-only operator disposition receipts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class DispositionReceiptPort(Protocol):
    def append(self, receipt: Mapping[str, object]) -> None:
        """Durably append one digest-sealed receipt row or raise."""
