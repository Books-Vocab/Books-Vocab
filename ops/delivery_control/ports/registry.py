from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.models import HandbackReceipt, MergedPullRequestProof
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
class RegistryCleanupQueryPort(Protocol):
    def find_exact_claim(
        self,
        *,
        lane_id: str,
        branch: str,
        path: Path,
        claim_generation: int,
    ) -> RegistrySnapshot | None: ...


@runtime_checkable
class RegistryTerminalQueryPort(Protocol):
    def find_terminal_claim(self, *, branch: str) -> RegistrySnapshot | None: ...


@runtime_checkable
class RegistryCommandPort(Protocol):
    def persist_handback(
        self, receipt: HandbackReceipt, *, expected_claim_generation: int
    ) -> None: ...

    def record_published_base(
        self,
        *,
        lane_id: str,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
        expected_handback_base_sha: str,
        published_base_sha: str,
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
        terminal_proof: MergedPullRequestProof | None = None,
    ) -> None: ...


@runtime_checkable
class RegistryDiscardCommandPort(Protocol):
    """Optional capability for the narrow abandoned-handback discard flow."""

    def discard(
        self,
        *,
        lane_id: str,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
        operator: str,
        reason: str,
    ) -> None: ...
