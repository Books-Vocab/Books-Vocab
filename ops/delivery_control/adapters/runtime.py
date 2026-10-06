"""Caller-supplied runtime facts and the optional receipt writer."""

from __future__ import annotations

import json
from dataclasses import replace
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from ..domain.errors import CompareAndSwapConflict, PolicyViolation
from ..domain.runtime_models import RuntimeReceipt
from .runtime_receipt import RuntimeReceiptFile, _UNSET


class RuntimeStatusMap:
    """Treat absent owner evidence as unknown; never dispatch from the CLI."""

    def __init__(
        self,
        statuses: Mapping[str, str] | None = None,
        receipts: Mapping[str, RuntimeReceipt] | None = None,
        *,
        path: Path | None = None,
    ) -> None:
        self.statuses = dict(statuses or {})
        self.receipts = dict(receipts or {})
        self._writer = RuntimeReceiptFile(path) if path is not None else None

    @classmethod
    def from_file(cls, path: Path | None) -> RuntimeStatusMap:
        if path is None:
            return cls()
        if not path.exists():
            # A missing receipt is an explicit unknown state.  The watchdog
            # converts it to ESCALATE; construction must not hide that fact
            # behind an I/O error.
            return cls(path=path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PolicyViolation(
                f"runtime status file is unreadable: {path}"
            ) from error
        if not isinstance(payload, Mapping):
            raise PolicyViolation("runtime status file must be a JSON object")
        if payload.get("schema") == "kg.delivery.runtime.v1":
            try:
                receipt = RuntimeReceipt.from_payload(payload)
            except ValueError as error:
                raise PolicyViolation("runtime receipt is malformed") from error
            return cls(
                {receipt.thread_id: receipt.state.value},
                {receipt.thread_id: receipt},
                path=path,
            )
        if any(
            type(key) is not str or type(value) is not str
            for key, value in payload.items()
        ):
            raise PolicyViolation("runtime status file must map thread IDs to states")
        return cls(payload, path=path)

    def owner_status(self, thread_id: str) -> str:
        if thread_id in self.statuses:
            return self.statuses[thread_id]
        receipt = self.receipts.get(thread_id)
        return receipt.state.value if receipt is not None else "unknown"

    def runtime_receipt(self, thread_id: str) -> RuntimeReceipt | None:
        return self.receipts.get(thread_id)

    def write(
        self,
        receipt: RuntimeReceipt,
        *,
        expected_cycle_id: str | None = None,
        expected_last_action_id: str | None | object = _UNSET,
    ) -> RuntimeReceipt:
        if self._writer is None:
            raise PolicyViolation("runtime receipt writes require a status file")
        written = self._writer.write(
            receipt,
            expected_cycle_id=expected_cycle_id,
            expected_last_action_id=expected_last_action_id,
        )
        self.statuses = {written.thread_id: written.state.value}
        self.receipts = {written.thread_id: written}
        return written

    def claim_wake(
        self,
        *,
        thread_id: str,
        wake_id: str,
        now: datetime,
        expected_cycle_id: str | None,
    ) -> RuntimeReceipt:
        """Atomically reserve one wake before an external scheduler dispatches."""

        if self._writer is None:
            raise PolicyViolation("runtime receipt writes require a status file")
        current = self.receipts.get(thread_id) or self._writer.read()
        if current is None:
            raise PolicyViolation("cannot claim a wake without a runtime receipt")
        if current.thread_id != thread_id:
            raise CompareAndSwapConflict(
                "runtime receipt thread changed before wake claim"
            )
        if current.last_action_id == wake_id:
            return current
        if current.last_action_id is not None:
            raise CompareAndSwapConflict("runtime receipt already has a wake claim")
        claimed = replace(
            current,
            observed_at=max(current.observed_at, now),
            last_action_id=wake_id,
        )
        written = self._writer.write(
            claimed,
            expected_cycle_id=expected_cycle_id,
            expected_last_action_id=None,
        )
        self.statuses = {written.thread_id: written.state.value}
        self.receipts = {written.thread_id: written}
        return written

    def dispatch(self, thread_id: str, instruction: str) -> None:
        raise PolicyViolation("the deterministic CLI never dispatches agents")
