"""Latency measurements derived from live registry, PR, and check timestamps."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..domain.inventory import DeliveryInventory
from ..domain.models import CheckStatus


@dataclass(frozen=True)
class PipelineTimings:
    handback_to_pr_samples: int = 0
    handback_to_pr_p95_seconds: float | None = None
    pr_to_required_start_samples: int = 0
    pr_to_required_start_p95_seconds: float | None = None
    required_duration_samples: int = 0
    required_duration_p95_seconds: float | None = None
    required_success_to_enqueue_samples: int = 0
    required_success_to_enqueue_p95_seconds: float | None = None
    invalid_samples: int = 0


def nearest_rank_percentile(
    values: tuple[float, ...], percentile: float
) -> float | None:
    if not values:
        return None
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def nearest_rank_p95(values: tuple[float, ...]) -> float | None:
    return nearest_rank_percentile(values, 0.95)


def _seconds_between(start, end) -> float | None:
    seconds = (end - start).total_seconds()
    return seconds if seconds >= 0 else None


def measure_pipeline_timings(inventory: DeliveryInventory) -> PipelineTimings:
    handback_to_pr: list[float] = []
    pr_to_required: list[float] = []
    required_duration: list[float] = []
    required_success_to_enqueue: list[float] = []
    invalid_samples = 0
    for lane in inventory.lanes:
        pull_request = lane.pull_requests[0] if len(lane.pull_requests) == 1 else None
        if (
            lane.registry is not None
            and lane.registry.handed_back_at is not None
            and pull_request is not None
            and pull_request.created_at is not None
        ):
            observed = _seconds_between(
                lane.registry.handed_back_at,
                pull_request.created_at,
            )
            if observed is None:
                invalid_samples += 1
            else:
                handback_to_pr.append(observed)
        check = lane.required_check
        if (
            pull_request is not None
            and pull_request.created_at is not None
            and check is not None
            and check.started_at is not None
        ):
            observed = _seconds_between(
                pull_request.created_at,
                check.started_at,
            )
            if observed is None:
                invalid_samples += 1
            else:
                pr_to_required.append(observed)
        if check is not None and check.duration_seconds is not None:
            required_duration.append(check.duration_seconds)
        if (
            check is not None
            and check.status is CheckStatus.SUCCESS
            and check.completed_at is not None
            and lane.queue_entry is not None
        ):
            observed = _seconds_between(
                check.completed_at,
                lane.queue_entry.enqueued_at,
            )
            if observed is None:
                invalid_samples += 1
            else:
                required_success_to_enqueue.append(observed)
    return PipelineTimings(
        handback_to_pr_samples=len(handback_to_pr),
        handback_to_pr_p95_seconds=nearest_rank_p95(tuple(handback_to_pr)),
        pr_to_required_start_samples=len(pr_to_required),
        pr_to_required_start_p95_seconds=nearest_rank_p95(tuple(pr_to_required)),
        required_duration_samples=len(required_duration),
        required_duration_p95_seconds=nearest_rank_p95(tuple(required_duration)),
        required_success_to_enqueue_samples=len(required_success_to_enqueue),
        required_success_to_enqueue_p95_seconds=nearest_rank_p95(
            tuple(required_success_to_enqueue)
        ),
        invalid_samples=invalid_samples,
    )
