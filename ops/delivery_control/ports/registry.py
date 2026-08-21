from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import HandbackReceipt
from ..domain.observations import (
    RegistryCollisionInventory,
    RegistryInventory,
    RegistrySnapshot,
)


@runtime_checkable
class RegistryQueryPort(Protocol):
    def list_records(self) -> RegistryInventory: ...

    def get(self, lane_id: str) -> RegistrySnapshot | None: ...


@runtime_checkable
class RegistryPublicationQueryPort(Protocol):
    def get(self, lane_id: str) -> RegistrySnapshot | None: ...

    def list_collision_claims(self) -> RegistryCollisionInventory: ...


@runtime_checkable
class RegistryCommandPort(Protocol):
    def persist_handback(
        self, receipt: HandbackReceipt, *, expected_claim_generation: int
    ) -> None: ...

    def resolve(
        self,
        lane_id: str,
        disposition: str,
        *,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
    ) -> None: ...
