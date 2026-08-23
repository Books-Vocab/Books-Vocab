"""Deterministic queue-depth and merge-cadence measurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

from ..domain.demand_issues import IssueDisposition
from ..domain.models import CheckStatus
from ..domain.states import LaneState
from ..domain.telemetry import TelemetryReadResult
from ..services.inspect import DeliveryInventory
from .timings import (
    PipelineTimings,
    measure_pipeline_timings,
    nearest_rank_p95,
    nearest_rank_percentile,
)


@dataclass(frozen=True)
class PipelineMetrics:
    active_development: int
    handbacks_publishable: int
    published_local_cleanup: int
    cleanup_pending: int
    open_prs: int
    unmapped_open_prs: int
    duplicate_pr_mappings: int
    required_green: int
    required_running: int
    required_failed: int
    required_absent: int
    pr_contract_failed: int
    merge_queue_depth: int
    terminal_cleanup: int
    blocked_lanes: int
    physical_worktrees: int
    source_problems: int
    candidate_issues: int
    reanchor_required: int
    dispatchable_candidate_issues: int | None = None
    raw_open_issues: int | None = 0
    unadmitted_open_issues: int | None = 0
    active_registry_records: int = 0
    raw_active_registry_records: int = 0
    active_registry_without_worktree: int = 0
    # Measured inventories split missing physical assets by whether the
    # original owner can actually be addressed. "None" preserves the
    # legacy direct-construction contract for callers that only provide the
    # aggregate metric.
    active_registry_without_worktree_owner_bound: int | None = None
    active_registry_without_worktree_ownerless: int | None = None
    malformed_active_registry_records: int = 0
    triage_required_issues: int = 0
    legacy_open_issues: int = 0
    issues_with_active_claim: int = 0
    issues_with_published_pr: int = 0
    issue_source_problems: int = 0
    issue_inventory_complete: bool = True
    clean_unregistered_worktrees: int = 0
    idle_worktrees: int = 0
    collision_lanes: int = 0
    security_hold_lanes: int = 0
    security_hold_issues: int = 0
    collision_rate: float = 0.0
    required_failure_rate: float = 0.0
    timings: PipelineTimings = field(default_factory=PipelineTimings)
    quarantined_source_problems: int = 0
    quarantined_blocked_lanes: int = 0
    quarantined_open_prs: int = 0
    quarantined_terminal_cleanup: int = 0
    actionable_source_problems: int | None = None
    actionable_blocked_lanes: int | None = None
    actionable_unmapped_open_prs: int | None = None
    actionable_terminal_cleanup: int | None = None
    recoverable_quarantine: int = field(init=False)
    backlog_drained: bool = field(init=False)
    pipeline_ready: bool = field(init=False)
    ramp_ready: bool = field(init=False)

    def __post_init__(self) -> None:
        # Direct construction predates isolation fields. Omitted actionability
        # is fully actionable; measured inventories provide explicit values.
        defaults = {
            "actionable_source_problems": self.source_problems,
            "actionable_blocked_lanes": self.blocked_lanes,
            "actionable_unmapped_open_prs": self.unmapped_open_prs,
            "actionable_terminal_cleanup": self.terminal_cleanup,
        }
        for field_name, value in defaults.items():
            if getattr(self, field_name) is None:
                object.__setattr__(self, field_name, value)
        if self.dispatchable_candidate_issues is None:
            object.__setattr__(
                self, "dispatchable_candidate_issues", self.candidate_issues
            )
        object.__setattr__(
            self,
            "recoverable_quarantine",
            self.quarantined_source_problems
            + self.quarantined_blocked_lanes
            + self.quarantined_open_prs
            + self.quarantined_terminal_cleanup,
        )
        pipeline_ready = (
            self.actionable_source_problems == 0
            and self.actionable_blocked_lanes == 0
            and self.actionable_unmapped_open_prs == 0
            and self.pr_contract_failed == 0
            and self.required_failed == 0
            and self.security_hold_lanes == 0
            and self.security_hold_issues == 0
        )
        backlog_drained = (
            self.issue_inventory_complete and self.unadmitted_open_issues == 0
        )
        object.__setattr__(self, "pipeline_ready", pipeline_ready)
        object.__setattr__(self, "backlog_drained", backlog_drained)
        object.__setattr__(self, "ramp_ready", pipeline_ready and backlog_drained)

    @property
    def quarantined_lanes(self) -> int:
        return self.quarantined_blocked_lanes + self.quarantined_terminal_cleanup


@dataclass(frozen=True)
class MergeCadence:
    window_seconds: int
    merged_count: int
    merges_per_hour: float
    p50_interval_seconds: float | None
    p95_interval_seconds: float | None
    seconds_since_last_merge: float | None


_BLOCKED = {
    LaneState.BLOCKED_COLLISION,
    LaneState.BLOCKED_DIRTY,
    LaneState.BLOCKED_DUPLICATE,
    LaneState.BLOCKED_OWNER,
    LaneState.UNKNOWN,
}


def measure_pipeline(
    inventory: DeliveryInventory,
    *,
    telemetry: TelemetryReadResult | None = None,
    now: datetime | None = None,
    excluded_worktree_paths: tuple[Path, ...] = (),
) -> PipelineMetrics:
    excluded_paths = {path.resolve() for path in excluded_worktree_paths}
    lanes = tuple(
        lane
        for lane in inventory.lanes
        if lane.physical is None or lane.physical.path.resolve() not in excluded_paths
    )
    measured_inventory = DeliveryInventory(
        lanes=lanes,
        source_problems=inventory.source_problems,
        candidate_issues=inventory.candidate_issues,
        dispatchable_candidate_issues=inventory.dispatchable_candidate_issues,
        demand_issues=inventory.demand_issues,
        isolation=inventory.isolation,
    )
    states = [lane.decision.state for lane in lanes]
    all_pull_request_numbers = {
        pull_request.number
        for lane in lanes
        for pull_request in lane.pull_requests
        if pull_request.state == "OPEN"
    }
    mapped_pull_request_numbers = {
        pull_request.number
        for lane in lanes
        if lane.registry is not None
        and lane.registry.status in {"active", "cleanup_pending", "published"}
        for pull_request in lane.pull_requests
        if pull_request.state == "OPEN"
    }
    physical_paths = {
        lane.physical.path.resolve() for lane in lanes if lane.physical is not None
    }
    active_registry_lanes = tuple(
        lane
        for lane in lanes
        if lane.registry is not None and lane.registry.status == "active"
    )
    malformed_active_registry_records = sum(
        problem.source == "registry" and problem.record_status == "active"
        for problem in inventory.source_problems
    )
    active_registry_records = len(active_registry_lanes)
    raw_active_registry_records = (
        active_registry_records + malformed_active_registry_records
    )
    active_registry_without_worktree = sum(
        lane.physical is None for lane in active_registry_lanes
    )
    active_registry_without_worktree_owner_bound = sum(
        lane.physical is None
        and bool(lane.registry is not None and lane.registry.owner_thread_id)
        for lane in active_registry_lanes
    )
    active_registry_without_worktree_ownerless = sum(
        lane.physical is None
        and not bool(lane.registry is not None and lane.registry.owner_thread_id)
        for lane in active_registry_lanes
    )
    collision_lanes = states.count(LaneState.BLOCKED_COLLISION)
    security_hold_lanes = states.count(LaneState.SECURITY_HOLD)
    live_states = [
        state
        for state in states
        if state not in {LaneState.DONE, LaneState.TERMINAL_CLEANUP}
    ]
    required_green = states.count(LaneState.READY_TO_QUEUE)
    required_running = sum(
        lane.required_check is not None
        and lane.required_check.status is CheckStatus.PENDING
        for lane in lanes
    )
    required_failed = sum(
        lane.required_check is not None
        and lane.required_check.status is CheckStatus.FAILURE
        for lane in lanes
    )
    required_absent = sum(
        lane.registry is not None
        and lane.registry.status in {"published", "cleanup_pending"}
        and lane.pull_requests
        and lane.pull_requests[0].state == "OPEN"
        and lane.required_check is not None
        and lane.required_check.status is CheckStatus.ABSENT
        for lane in lanes
    )
    required_succeeded = sum(
        lane.required_check is not None
        and lane.required_check.status is CheckStatus.SUCCESS
        for lane in lanes
    )
    required_terminal = required_succeeded + required_failed
    pr_contract_failed = states.count(LaneState.PR_CONTRACT_FAILED)
    handbacks_publishable = states.count(LaneState.HANDBACK_PUBLISHABLE)
    published_local_cleanup = states.count(LaneState.PUBLISHED_LOCAL_CLEANUP)
    clean_unregistered_worktrees = sum(
        lane.registry is None
        and lane.physical is not None
        and lane.snapshot is not None
        and lane.snapshot.clean
        for lane in lanes
    )
    unknown_unregistered_worktrees = sum(
        lane.registry is None and lane.physical is not None and lane.snapshot is None
        for lane in lanes
    )
    timings = measure_pipeline_timings(measured_inventory, telemetry=telemetry, now=now)
    isolation = inventory.isolation
    unknown_source_problems = unknown_unregistered_worktrees
    invalid_source_problems = timings.invalid_samples + (
        len(telemetry.problems) if telemetry is not None else 0
    )
    # A malformed raw entry is represented by both an evidence problem and a
    # typed SOURCE_PROBLEM partition. Count the partition once so source
    # metrics cannot exceed the raw Issue inventory.
    issue_source_problems = inventory.demand_issues.count(
        IssueDisposition.SOURCE_PROBLEM
    )
    issue_inventory_problem = int(not inventory.demand_issues.complete)
    total_source_problems = (
        len(inventory.source_problems)
        + invalid_source_problems
        + unknown_source_problems
        + issue_source_problems
        + issue_inventory_problem
    )
    return PipelineMetrics(
        active_development=states.count(LaneState.ACTIVE_DEVELOPMENT),
        handbacks_publishable=handbacks_publishable,
        published_local_cleanup=published_local_cleanup,
        cleanup_pending=sum(
            lane.registry is not None and lane.registry.status == "cleanup_pending"
            for lane in lanes
        ),
        open_prs=len(mapped_pull_request_numbers),
        unmapped_open_prs=len(all_pull_request_numbers - mapped_pull_request_numbers),
        duplicate_pr_mappings=states.count(LaneState.BLOCKED_DUPLICATE),
        required_green=required_green,
        required_running=required_running,
        required_failed=required_failed,
        required_absent=required_absent,
        pr_contract_failed=pr_contract_failed,
        merge_queue_depth=states.count(LaneState.PR_QUEUED),
        terminal_cleanup=states.count(LaneState.TERMINAL_CLEANUP),
        blocked_lanes=sum(state in _BLOCKED for state in states),
        physical_worktrees=len(physical_paths),
        source_problems=total_source_problems,
        candidate_issues=len(inventory.candidate_issues),
        dispatchable_candidate_issues=len(inventory.dispatchable_candidate_issues),
        raw_open_issues=inventory.demand_issues.raw_open_issues,
        unadmitted_open_issues=inventory.demand_issues.unadmitted_open_issues,
        active_registry_records=active_registry_records,
        raw_active_registry_records=raw_active_registry_records,
        active_registry_without_worktree=active_registry_without_worktree,
        active_registry_without_worktree_owner_bound=(
            active_registry_without_worktree_owner_bound
        ),
        active_registry_without_worktree_ownerless=(
            active_registry_without_worktree_ownerless
        ),
        malformed_active_registry_records=malformed_active_registry_records,
        triage_required_issues=inventory.demand_issues.count(
            IssueDisposition.TRIAGE_REQUIRED
        ),
        legacy_open_issues=inventory.demand_issues.count(
            IssueDisposition.LEGACY_UNMAPPED
        ),
        issues_with_active_claim=inventory.demand_issues.count(
            IssueDisposition.OWNER_BOUND
        ),
        issues_with_published_pr=inventory.demand_issues.count(
            IssueDisposition.PUBLISHED_PR
        ),
        issue_source_problems=(issue_source_problems + issue_inventory_problem),
        issue_inventory_complete=inventory.demand_issues.complete,
        reanchor_required=states.count(LaneState.REANCHOR),
        clean_unregistered_worktrees=clean_unregistered_worktrees,
        idle_worktrees=(
            handbacks_publishable
            + published_local_cleanup
            + clean_unregistered_worktrees
        ),
        collision_lanes=collision_lanes,
        collision_rate=(collision_lanes / len(live_states) if live_states else 0.0),
        security_hold_lanes=security_hold_lanes,
        security_hold_issues=inventory.demand_issues.count(
            IssueDisposition.SECURITY_HOLD
        ),
        required_failure_rate=(
            required_failed / required_terminal if required_terminal else 0.0
        ),
        timings=timings,
        quarantined_source_problems=isolation.quarantined_source_problems,
        quarantined_blocked_lanes=isolation.quarantined_blocked_lanes,
        quarantined_open_prs=isolation.quarantined_open_prs,
        quarantined_terminal_cleanup=isolation.quarantined_terminal_cleanup,
        actionable_source_problems=max(
            0,
            total_source_problems - isolation.quarantined_source_problems,
        ),
        actionable_blocked_lanes=max(
            0,
            sum(state in _BLOCKED for state in states)
            - isolation.quarantined_blocked_lanes
            - isolation.quarantined_open_prs,
        ),
        actionable_unmapped_open_prs=max(
            0,
            len(all_pull_request_numbers - mapped_pull_request_numbers)
            - isolation.quarantined_open_prs,
        ),
        actionable_terminal_cleanup=max(
            0,
            states.count(LaneState.TERMINAL_CLEANUP)
            - isolation.quarantined_terminal_cleanup,
        ),
    )


def measure_merge_cadence(
    merged_at: tuple[datetime, ...],
    *,
    now: datetime,
    window: timedelta = timedelta(hours=1),
) -> MergeCadence:
    if now.utcoffset() is None or window.total_seconds() <= 0:
        raise ValueError("merge cadence requires aware now and positive window")
    start = now - window
    selected = tuple(
        sorted(
            timestamp
            for timestamp in merged_at
            if timestamp.utcoffset() is not None and start <= timestamp <= now
        )
    )
    intervals = tuple(
        (right - left).total_seconds() for left, right in pairwise(selected)
    )
    seconds = int(window.total_seconds())
    rate = len(selected) * 3600 / seconds
    return MergeCadence(
        window_seconds=seconds,
        merged_count=len(selected),
        merges_per_hour=rate,
        p50_interval_seconds=nearest_rank_percentile(intervals, 0.5),
        p95_interval_seconds=nearest_rank_p95(intervals),
        seconds_since_last_merge=(
            (now - selected[-1]).total_seconds() if selected else None
        ),
    )
