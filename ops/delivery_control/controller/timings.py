"""Rolling latency measurements from live facts plus duration telemetry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..domain.inventory import DeliveryInventory
from ..domain.models import CheckStatus
from ..domain.telemetry import (
    DurationSample,
    TelemetryMetric,
    TelemetryReadResult,
    publication_subject,
    pull_request_subject,
    queue_subject,
    sample_key_for,
)


@dataclass(frozen=True)
class PipelineTimings:
    window_seconds: int = 3600
    handback_to_pr_samples: int = 0
    handback_to_pr_p95_seconds: float | None = None
    pr_to_required_start_samples: int = 0
    pr_to_required_start_p95_seconds: float | None = None
    required_duration_samples: int = 0
    required_duration_p95_seconds: float | None = None
    required_success_to_enqueue_samples: int = 0
    required_success_to_enqueue_p95_seconds: float | None = None
    merge_to_sync_samples: int = 0
    merge_to_sync_p95_seconds: float | None = None
    merge_to_cleanup_samples: int = 0
    merge_to_cleanup_p95_seconds: float | None = None
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


def _default_now(inventory: DeliveryInventory) -> datetime:
    observed: list[datetime] = []
    for lane in inventory.lanes:
        if lane.registry is not None and lane.registry.handed_back_at is not None:
            observed.append(lane.registry.handed_back_at)
        for pull_request in lane.pull_requests:
            observed.extend(
                item
                for item in (pull_request.created_at, pull_request.merged_at)
                if item is not None
            )
        if lane.required_check is not None:
            observed.extend(
                item
                for item in (
                    lane.required_check.observed_at,
                    lane.required_check.started_at,
                    lane.required_check.completed_at,
                )
                if item is not None
            )
        if lane.queue_entry is not None:
            observed.append(lane.queue_entry.enqueued_at)
    return max(observed, default=datetime.now(tz=UTC))


def _publication_time_for_required_check(
    *,
    publication_sample: DurationSample | None,
    initial_publication_at: datetime | None,
    required_started_at: datetime | None,
) -> datetime | None:
    """Choose a publication anchor that is valid for this required check.

    A same-PR re-publication can be recorded after the required check has
    already started.  That immutable sample remains useful evidence, but it
    cannot be used as the start of a non-negative transport interval.
    """
    if required_started_at is None:
        return None
    if (
        publication_sample is not None
        and publication_sample.completed_at <= required_started_at
    ):
        return publication_sample.completed_at
    if (
        initial_publication_at is not None
        and initial_publication_at <= required_started_at
    ):
        return initial_publication_at
    return None


def measure_pipeline_timings(
    inventory: DeliveryInventory,
    *,
    telemetry: TelemetryReadResult | None = None,
    now: datetime | None = None,
    window: timedelta = timedelta(hours=1),
) -> PipelineTimings:
    observed_at = now or _default_now(inventory)
    if observed_at.utcoffset() is None or window.total_seconds() <= 0:
        raise ValueError("timing window requires aware now and positive duration")
    cutoff = observed_at - window
    samples: dict[str, DurationSample] = {
        sample.sample_key: sample
        for sample in (telemetry.samples if telemetry is not None else ())
        if cutoff <= sample.completed_at <= observed_at
    }
    invalid_samples = 0

    def add_live(sample: DurationSample) -> None:
        if cutoff <= sample.completed_at <= observed_at:
            # Journal evidence is the exact command readback and takes
            # precedence over a reconstructable live observation.
            samples.setdefault(sample.sample_key, sample)

    def observe(
        metric: TelemetryMetric,
        subject: str,
        started_at: datetime | None,
        completed_at: datetime | None,
    ) -> None:
        nonlocal invalid_samples
        if started_at is None or completed_at is None:
            return
        try:
            add_live(DurationSample(metric, subject, started_at, completed_at))
        except ValueError:
            invalid_samples += 1

    for lane in inventory.lanes:
        pull_request = lane.pull_requests[0] if len(lane.pull_requests) == 1 else None
        handed_back_at = (
            lane.registry.handed_back_at if lane.registry is not None else None
        )
        pr_created_at = pull_request.created_at if pull_request is not None else None
        # PR.created_at measures initial publication only. A later handback is a
        # normal same-PR JIT reanchor, not a negative transport latency.
        if (
            handed_back_at is not None
            and pr_created_at is not None
            and handed_back_at <= pr_created_at
            and lane.registry is not None
            and pull_request is not None
        ):
            observe(
                TelemetryMetric.HANDBACK_TO_PR,
                publication_subject(
                    lane_id=lane.registry.lane_id,
                    claim_generation=lane.registry.claim_generation,
                    head_sha=pull_request.head_sha,
                    pr_number=pull_request.number,
                ),
                handed_back_at,
                pr_created_at,
            )
        check = lane.required_check
        if pull_request is not None and check is not None:
            pr_subject = pull_request_subject(
                pr_number=pull_request.number,
                head_sha=pull_request.head_sha,
            )
            publication_key = None
            if lane.registry is not None:
                publication_key = sample_key_for(
                    TelemetryMetric.HANDBACK_TO_PR,
                    publication_subject(
                        lane_id=lane.registry.lane_id,
                        claim_generation=lane.registry.claim_generation,
                        head_sha=pull_request.head_sha,
                        pr_number=pull_request.number,
                    ),
                )
            publication_sample = (
                samples.get(publication_key) if publication_key is not None else None
            )
            initial_publication_at = (
                pull_request.created_at
                if (
                    handed_back_at is not None
                    and pull_request.created_at is not None
                    and handed_back_at <= pull_request.created_at
                )
                else None
            )
            publication_time = _publication_time_for_required_check(
                publication_sample=publication_sample,
                initial_publication_at=initial_publication_at,
                required_started_at=check.started_at,
            )
            observe(
                TelemetryMetric.PR_TO_REQUIRED_START,
                pr_subject,
                publication_time,
                check.started_at,
            )
            observe(
                TelemetryMetric.REQUIRED_DURATION,
                pr_subject,
                check.started_at,
                check.completed_at,
            )
        if (
            pull_request is not None
            and check is not None
            and check.status is CheckStatus.SUCCESS
            and check.completed_at is not None
            and lane.queue_entry is not None
        ):
            observe(
                TelemetryMetric.REQUIRED_SUCCESS_TO_ENQUEUE,
                queue_subject(
                    pr_number=pull_request.number,
                    head_sha=pull_request.head_sha,
                    queue_entry_id=lane.queue_entry.entry_id,
                ),
                check.completed_at,
                lane.queue_entry.enqueued_at,
            )

    grouped = {
        metric: tuple(
            sample.duration_seconds
            for sample in samples.values()
            if sample.metric is metric
        )
        for metric in TelemetryMetric
    }

    def count(metric: TelemetryMetric) -> int:
        return len(grouped[metric])

    def p95(metric: TelemetryMetric) -> float | None:
        return nearest_rank_p95(grouped[metric])

    return PipelineTimings(
        window_seconds=int(window.total_seconds()),
        handback_to_pr_samples=count(TelemetryMetric.HANDBACK_TO_PR),
        handback_to_pr_p95_seconds=p95(TelemetryMetric.HANDBACK_TO_PR),
        pr_to_required_start_samples=count(TelemetryMetric.PR_TO_REQUIRED_START),
        pr_to_required_start_p95_seconds=p95(TelemetryMetric.PR_TO_REQUIRED_START),
        required_duration_samples=count(TelemetryMetric.REQUIRED_DURATION),
        required_duration_p95_seconds=p95(TelemetryMetric.REQUIRED_DURATION),
        required_success_to_enqueue_samples=count(
            TelemetryMetric.REQUIRED_SUCCESS_TO_ENQUEUE
        ),
        required_success_to_enqueue_p95_seconds=p95(
            TelemetryMetric.REQUIRED_SUCCESS_TO_ENQUEUE
        ),
        merge_to_sync_samples=count(TelemetryMetric.MERGE_TO_SYNC),
        merge_to_sync_p95_seconds=p95(TelemetryMetric.MERGE_TO_SYNC),
        merge_to_cleanup_samples=count(TelemetryMetric.MERGE_TO_CLEANUP),
        merge_to_cleanup_p95_seconds=p95(TelemetryMetric.MERGE_TO_CLEANUP),
        invalid_samples=invalid_samples,
    )
