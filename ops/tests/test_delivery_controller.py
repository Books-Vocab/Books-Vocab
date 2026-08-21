from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.controller.capacity import ControlAction, decide_capacity
from delivery_control.controller.metrics import (
    PipelineMetrics,
    measure_merge_cadence,
    measure_pipeline,
)
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import PullRequestSnapshot, RegistrySnapshot
from delivery_control.domain.states import LaneDecision, LaneState, NextAction
from delivery_control.services.inspect import DeliveryInventory, LaneInspection


def _metrics(**changes: int) -> PipelineMetrics:
    values = {
        "active_development": 0,
        "handbacks_publishable": 0,
        "published_local_cleanup": 0,
        "open_prs": 0,
        "unmapped_open_prs": 0,
        "required_green": 0,
        "required_failed": 0,
        "terminal_cleanup": 0,
        "blocked_lanes": 0,
        "physical_worktrees": 0,
        "source_problems": 0,
    }
    values.update(changes)
    return PipelineMetrics(**values)


def test_merge_cadence_measures_hourly_rate_and_nearest_rank_p95() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    merged = tuple(
        now - timedelta(minutes=offset) for offset in (25, 20, 15, 10, 5)
    )

    cadence = measure_merge_cadence(merged, now=now)

    assert cadence.merged_count == 5
    assert cadence.merges_per_hour == 5.0
    assert cadence.p95_interval_seconds == 300.0
    assert cadence.seconds_since_last_merge == 300.0


def test_controller_drains_every_existing_reservoir_without_serializing() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            handbacks_publishable=2,
            published_local_cleanup=1,
            required_green=1,
            required_failed=1,
            terminal_cleanup=1,
            blocked_lanes=1,
        ),
        cadence,
    )

    assert ControlAction.PUBLISH_HANDBACKS in decision.actions
    assert ControlAction.CLEANUP_LOCAL in decision.actions
    assert ControlAction.ENQUEUE_GREEN in decision.actions
    assert ControlAction.REPAIR_REQUIRED in decision.actions
    assert ControlAction.CLEANUP_TERMINAL in decision.actions
    assert ControlAction.RECOVER_BLOCKERS in decision.actions
    assert decision.desired_new_solvers == 4


def test_controller_throttles_solver_birth_when_ci_is_saturated() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(active_development=1, open_prs=3),
        cadence,
        required_p95_seconds=500,
    )

    assert ControlAction.THROTTLE_SOLVERS in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0


def test_controller_reports_source_uncertainty_instead_of_fabricating_supply() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(_metrics(source_problems=2), cadence)
    assert ControlAction.INSPECT_SOURCES in decision.actions
    assert ControlAction.RECOVER_BLOCKERS in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0


def test_pipeline_supply_counts_only_owner_mapped_open_prs() -> None:
    pull_request = PullRequestSnapshot(
        number=7,
        url="https://example.test/pull/7",
        branch="feat/one",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
    )
    record = RegistrySnapshot(
        lane_id="#1",
        branch="feat/one",
        path=Path("/tmp/one"),
        status="published",
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha="a" * 40,
        claim_generation=1,
    )
    waiting = LaneDecision(
        LaneState.PR_WAITING_REQUIRED,
        NextAction.WAIT_REQUIRED,
        "waiting",
    )
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key="#1",
                registry=record,
                physical=None,
                snapshot=None,
                pull_requests=(pull_request,),
                decision=waiting,
            ),
            LaneInspection(
                key="PR#8",
                registry=None,
                physical=None,
                snapshot=None,
                pull_requests=(replace(pull_request, number=8),),
                decision=LaneDecision(
                    LaneState.UNKNOWN, NextAction.INSPECT, "unmapped"
                ),
            ),
        )
    )

    metrics = measure_pipeline(inventory)

    assert metrics.open_prs == 1
    assert metrics.unmapped_open_prs == 1
