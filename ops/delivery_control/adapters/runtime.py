"""Read-only agent runtime facts supplied by the caller."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ..domain.errors import PolicyViolation


class RuntimeStatusMap:
    """Treat absent owner evidence as unknown; never dispatch from the CLI."""

    def __init__(self, statuses: Mapping[str, str] | None = None) -> None:
        self.statuses = dict(statuses or {})

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
        if not isinstance(payload, Mapping) or any(
            type(key) is not str or type(value) is not str
            for key, value in payload.items()
        ):
            raise PolicyViolation(
                "runtime status file must map thread IDs to states"
            )
        return cls(payload)

    def owner_status(self, thread_id: str) -> str:
        return self.statuses.get(thread_id, "unknown")

    def dispatch(self, thread_id: str, instruction: str) -> None:
        raise PolicyViolation("the deterministic CLI never dispatches agents")
