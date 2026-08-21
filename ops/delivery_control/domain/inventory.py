"""Typed outputs produced by delivery inventory projection."""

from __future__ import annotations

from dataclasses import dataclass

from .observations import (
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from .states import LaneDecision


@dataclass(frozen=True)
class LaneInspection:
    key: str
    registry: RegistrySnapshot | None
    physical: PhysicalWorktree | None
    snapshot: WorktreeSnapshot | None
    pull_requests: tuple[PullRequestSnapshot, ...]
    decision: LaneDecision
    problems: tuple[InventoryProblem, ...] = ()


@dataclass(frozen=True)
class DeliveryInventory:
    lanes: tuple[LaneInspection, ...]
    source_problems: tuple[InventoryProblem, ...] = ()
