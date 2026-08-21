"""Deterministic queue-depth and merge-cadence measurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

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
    pr_contract_failed: int
    merge_queue_depth: int
    terminal_cleanup: int
    blocked_lanes: int
    physical_worktrees: int
    source_problems: int
    idle_worktrees: int = 0
    collision_lanes: int = 0
    collision_rate: float = 0.0
    required_failure_rate: float = 0.0
    timings: PipelineTimings = field(default_factory=PipelineTimings)


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
) -> PipelineMetrics:
    states = [lane.decision.state for lane in inventory.lanes]
    all_pull_request_numbers = {
        pull_request.number
        for lane in inventory.lanes
        for pull_request in lane.pull_requests
        if pull_request.state == "OPEN"
    }
    mapped_pull_request_numbers = {
        pull_request.number
        for lane in inventory.lanes
        if lane.registry is not None
        and lane.registry.status in {"active", "cleanup_pending", "published"}
        for pull_request in lane.pull_requests
        if pull_request.state == "OPEN"
    }
    physical_paths = {
        lane.physical.path.resolve()
        for lane in inventory.lanes
        if lane.physical is not None
    }
    collision_lanes = states.count(LaneState.BLOCKED_COLLISION)
    live_states = [
        state
        for state in states
        if state not in {LaneState.DONE, LaneState.TERMINAL_CLEANUP}
    ]
    required_green = states.count(LaneState.READY_TO_QUEUE)
    required_running = sum(
        lane.required_check is not None
        and lane.required_check.status is CheckStatus.PENDING
        for lane in inventory.lanes
    )
    required_failed = sum(
        lane.required_check is not None
        and lane.required_check.status is CheckStatus.FAILURE
        for lane in inventory.lanes
    )
    required_succeeded = sum(
        lane.required_check is not None
        and lane.required_check.status is CheckStatus.SUCCESS
        for lane in inventory.lanes
    )
    required_terminal = required_succeeded + required_failed
    pr_contract_failed = states.count(LaneState.PR_CONTRACT_FAILED)
    handbacks_publishable = states.count(LaneState.HANDBACK_PUBLISHABLE)
    published_local_cleanup = states.count(LaneState.PUBLISHED_LOCAL_CLEANUP)
    timings = measure_pipeline_timings(inventory, telemetry=telemetry, now=now)
    return PipelineMetrics(
        active_development=states.count(LaneState.ACTIVE_DEVELOPMENT),
        handbacks_publishable=handbacks_publishable,
        published_local_cleanup=published_local_cleanup,
        cleanup_pending=sum(
            lane.registry is not None and lane.registry.status == "cleanup_pending"
            for lane in inventory.lanes
        ),
        open_prs=len(mapped_pull_request_numbers),
        unmapped_open_prs=len(all_pull_request_numbers - mapped_pull_request_numbers),
        duplicate_pr_mappings=states.count(LaneState.BLOCKED_DUPLICATE),
        required_green=required_green,
        required_running=required_running,
        required_failed=required_failed,
        pr_contract_failed=pr_contract_failed,
        merge_queue_depth=states.count(LaneState.PR_QUEUED),
        terminal_cleanup=states.count(LaneState.TERMINAL_CLEANUP),
        blocked_lanes=sum(state in _BLOCKED for state in states),
        physical_worktrees=len(physical_paths),
        source_problems=(
            len(inventory.source_problems)
            + timings.invalid_samples
            + (len(telemetry.problems) if telemetry is not None else 0)
        ),
        idle_worktrees=handbacks_publishable + published_local_cleanup,
        collision_lanes=collision_lanes,
        collision_rate=(collision_lanes / len(live_states) if live_states else 0.0),
        required_failure_rate=(
            required_failed / required_terminal if required_terminal else 0.0
        ),
        timings=timings,
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
