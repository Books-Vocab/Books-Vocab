from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.controller.metrics import measure_pipeline
from delivery_control.controller.timings import measure_pipeline_timings
from delivery_control.domain.inventory import DeliveryInventory, LaneInspection
from delivery_control.domain.models import CheckStatus, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
    MergeQueueEntrySnapshot,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.domain.states import LaneDecision, LaneState, NextAction


def _inventory(*, created_offset_seconds: int = 30) -> DeliveryInventory:
    start = datetime(2026, 8, 21, tzinfo=UTC)
    registry = RegistrySnapshot(
        lane_id="ISSUE-1",
        branch="feat/one",
        path=Path("/tmp/one"),
        status="published",
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha="a" * 40,
        claim_generation=1,
        handed_back_at=start,
    )
    pull_request = PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch="feat/one",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
        created_at=start + timedelta(seconds=created_offset_seconds),
    )
    check = CheckSnapshot(
        status=CheckStatus.SUCCESS,
        head_sha="b" * 40,
        observed_at=start + timedelta(seconds=180),
        names=("required",),
        started_at=start + timedelta(seconds=40),
        completed_at=start + timedelta(seconds=160),
    )
    return DeliveryInventory(
        lanes=(
            LaneInspection(
                key="ISSUE-1",
                registry=registry,
                physical=None,
                snapshot=None,
                pull_requests=(pull_request,),
                decision=LaneDecision(
                    LaneState.READY_TO_QUEUE,
                    NextAction.ENQUEUE,
                    "ready",
                ),
                required_check=check,
                queue_entry=MergeQueueEntrySnapshot(
                    "MQE_1", start + timedelta(seconds=170)
                ),
            ),
        )
    )


def test_pipeline_timings_measure_live_handback_pr_and_required_latency() -> None:
    timings = measure_pipeline_timings(_inventory())

    assert timings.handback_to_pr_samples == 1
    assert timings.handback_to_pr_p95_seconds == 30.0
    assert timings.pr_to_required_start_samples == 1
    assert timings.pr_to_required_start_p95_seconds == 10.0
    assert timings.required_duration_samples == 1
    assert timings.required_duration_p95_seconds == 120.0
    assert timings.required_success_to_enqueue_samples == 1
    assert timings.required_success_to_enqueue_p95_seconds == 10.0


def test_pipeline_metrics_expose_required_failure_and_collision_rates() -> None:
    inventory = _inventory()
    ready = inventory.lanes[0]
    failed = replace(
        ready,
        key="ISSUE-2",
        decision=LaneDecision(
            LaneState.REQUIRED_FAILED,
            NextAction.REPAIR_REQUIRED,
            "failed",
        ),
        required_check=replace(
            ready.required_check,
            status=CheckStatus.FAILURE,
        ),
    )
    contract_failed = replace(
        ready,
        key="ISSUE-3",
        decision=LaneDecision(
            LaneState.PR_CONTRACT_FAILED,
            NextAction.REPAIR_PR_CONTRACT,
            "contract failed",
        ),
    )
    collision = LaneInspection(
        key="ISSUE-4",
        registry=None,
        physical=None,
        snapshot=None,
        pull_requests=(),
        decision=LaneDecision(
            LaneState.BLOCKED_COLLISION,
            NextAction.RESOLVE_COLLISION,
            "collision",
        ),
    )

    metrics = measure_pipeline(
        DeliveryInventory(lanes=(ready, failed, contract_failed, collision))
    )

    assert metrics.required_failure_rate == pytest.approx(1 / 3)
    assert metrics.required_failed == 1
    assert metrics.pr_contract_failed == 1
    assert metrics.collision_lanes == 1
    assert metrics.collision_rate == pytest.approx(1 / 4)
    assert metrics.timings.required_duration_p95_seconds == 120.0


def test_jit_reanchor_excludes_initial_publication_latency_without_source_problem() -> (
    None
):
    inventory = _inventory(created_offset_seconds=-1)

    timings = measure_pipeline_timings(inventory)
    metrics = measure_pipeline(inventory)

    assert timings.invalid_samples == 0
    assert timings.handback_to_pr_samples == 0
    assert metrics.source_problems == 0
