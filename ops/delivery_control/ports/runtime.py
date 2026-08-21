from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentRuntimePort(Protocol):
    def owner_status(self, thread_id: str) -> str: ...

    def dispatch(self, thread_id: str, instruction: str) -> None: ...
