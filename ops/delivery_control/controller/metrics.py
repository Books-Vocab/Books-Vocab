"""Deterministic queue-depth and merge-cadence measurements."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..domain.states import LaneState
from ..services.inspect import DeliveryInventory


@dataclass(frozen=True)
class PipelineMetrics:
    active_development: int
    handbacks_publishable: int
    published_local_cleanup: int
    open_prs: int
    unmapped_open_prs: int
    required_green: int
    required_failed: int
    terminal_cleanup: int
    blocked_lanes: int
    physical_worktrees: int
    source_problems: int


@dataclass(frozen=True)
class MergeCadence:
    window_seconds: int
    merged_count: int
    merges_per_hour: float
    p95_interval_seconds: float | None
    seconds_since_last_merge: float | None


_BLOCKED = {
    LaneState.BLOCKED_COLLISION,
    LaneState.BLOCKED_DIRTY,
    LaneState.BLOCKED_DUPLICATE,
    LaneState.BLOCKED_OWNER,
    LaneState.UNKNOWN,
}


def measure_pipeline(inventory: DeliveryInventory) -> PipelineMetrics:
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
        and lane.registry.status in {"active", "published"}
        for pull_request in lane.pull_requests
        if pull_request.state == "OPEN"
    }
    physical_paths = {
        lane.physical.path.resolve()
        for lane in inventory.lanes
        if lane.physical is not None
    }
    return PipelineMetrics(
        active_development=states.count(LaneState.ACTIVE_DEVELOPMENT),
        handbacks_publishable=states.count(LaneState.HANDBACK_PUBLISHABLE),
        published_local_cleanup=states.count(LaneState.PUBLISHED_LOCAL_CLEANUP),
        open_prs=len(mapped_pull_request_numbers),
        unmapped_open_prs=len(
            all_pull_request_numbers - mapped_pull_request_numbers
        ),
        required_green=states.count(LaneState.READY_TO_QUEUE),
        required_failed=states.count(LaneState.REQUIRED_FAILED),
        terminal_cleanup=states.count(LaneState.TERMINAL_CLEANUP),
        blocked_lanes=sum(state in _BLOCKED for state in states),
        physical_worktrees=len(physical_paths),
        source_problems=len(inventory.source_problems),
    )


def _nearest_rank_p95(values: tuple[float, ...]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


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
        (right - left).total_seconds()
        for left, right in zip(selected, selected[1:], strict=False)
    )
    seconds = int(window.total_seconds())
    rate = len(selected) * 3600 / seconds
    return MergeCadence(
        window_seconds=seconds,
        merged_count=len(selected),
        merges_per_hour=rate,
        p95_interval_seconds=_nearest_rank_p95(intervals),
        seconds_since_last_merge=(
            (now - selected[-1]).total_seconds() if selected else None
        ),
    )
