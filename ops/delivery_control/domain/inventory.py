"""Typed outputs produced by delivery inventory projection."""

from __future__ import annotations

from dataclasses import dataclass

from .candidate_issues import CandidateIssue
from .demand_issues import EMPTY_DEMAND_INVENTORY, DemandIssueInventory
from .isolation import EMPTY_ISOLATION, IsolationSummary
from .observations import (
    CheckSnapshot,
    InventoryProblem,
    MergeQueueEntrySnapshot,
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
    required_check: CheckSnapshot | None = None
    queue_entry: MergeQueueEntrySnapshot | None = None


@dataclass(frozen=True)
class DeliveryInventory:
    lanes: tuple[LaneInspection, ...]
    source_problems: tuple[InventoryProblem, ...] = ()
    candidate_issues: tuple[CandidateIssue, ...] = ()
    dispatchable_candidate_issues: tuple[CandidateIssue, ...] = ()
    demand_issues: DemandIssueInventory = EMPTY_DEMAND_INVENTORY
    isolation: IsolationSummary = EMPTY_ISOLATION
