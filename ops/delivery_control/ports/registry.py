from __future__ import annotations

from typing import Protocol, runtime_checkable

from delivery_control.domain.models import RegistrySnapshot


@runtime_checkable
class RegistryQueryPort(Protocol):
    def list_active(self) -> tuple[RegistrySnapshot, ...]: ...

    def get(self, lane_id: str) -> RegistrySnapshot | None: ...


@runtime_checkable
class RegistryCommandPort(Protocol):
    def persist_handback(self, lane_id: str, payload: dict[str, object]) -> None: ...

    def resolve(self, lane_id: str, disposition: str) -> None: ...
