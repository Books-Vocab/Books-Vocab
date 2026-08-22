"""Read-only agent runtime facts supplied by the caller."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ..domain.errors import PolicyViolation
from ..domain.runtime_models import RuntimeReceipt


class RuntimeStatusMap:
    """Treat absent owner evidence as unknown; never dispatch from the CLI."""

    def __init__(
        self,
        statuses: Mapping[str, str] | None = None,
        receipts: Mapping[str, RuntimeReceipt] | None = None,
    ) -> None:
        self.statuses = dict(statuses or {})
        self.receipts = dict(receipts or {})

    @classmethod
    def from_file(cls, path: Path | None) -> RuntimeStatusMap:
        if path is None:
            return cls()
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
            return cls({receipt.thread_id: receipt.state.value}, {receipt.thread_id: receipt})
        if any(
            type(key) is not str or type(value) is not str
            for key, value in payload.items()
        ):
            raise PolicyViolation("runtime status file must map thread IDs to states")
        return cls(payload)

    def owner_status(self, thread_id: str) -> str:
        if thread_id in self.statuses:
            return self.statuses[thread_id]
        receipt = self.receipts.get(thread_id)
        return receipt.state.value if receipt is not None else "unknown"

    def runtime_receipt(self, thread_id: str) -> RuntimeReceipt | None:
        return self.receipts.get(thread_id)

    def dispatch(self, thread_id: str, instruction: str) -> None:
        raise PolicyViolation("the deterministic CLI never dispatches agents")
