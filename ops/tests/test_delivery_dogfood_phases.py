from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

# The test imports the in-repository package after extending sys.path so it can
# run from the repository's ops test harness.
OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.cli import _jsonable, _parser
from delivery_control.controller.dogfood import (
    DogfoodProfile,
    DogfoodReadiness,
)
from delivery_control.controller.metrics import MergeCadence, PipelineMetrics
from delivery_control.controller.phase_readiness import (
    DogfoodMode,
    assess_phase_readiness,
)
from delivery_control.controller.timings import PipelineTimings


def _metrics(**changes: object) -> PipelineMetrics:
    values: dict[str, object] = {
        "active_development": 0,
        "handbacks_publishable": 0,
        "published_local_cleanup": 0,
        "cleanup_pending": 0,
        "open_prs": 0,
        "unmapped_open_prs": 0,
        "duplicate_pr_mappings": 0,
        "required_green": 0,
        "required_running": 0,
        "required_failed": 0,
        "required_absent": 0,
        "pr_contract_failed": 0,
        "merge_queue_depth": 0,
        "terminal_cleanup": 0,
        "blocked_lanes": 0,
        "physical_worktrees": 1,
        "source_problems": 0,
        "candidate_issues": 1,
        "reanchor_required": 0,
        "raw_open_issues": 1,
        "unadmitted_open_issues": 0,
        "issue_inventory_complete": True,
        "clean_unregistered_worktrees": 0,
        "security_hold_lanes": 0,
        "security_hold_issues": 0,
        "timings": PipelineTimings(),
    }
    values.update(changes)
    return PipelineMetrics(**values)  # type: ignore[arg-type]


def _base(
    metrics: PipelineMetrics,
    *,
    cadence: MergeCadence | None = None,
    ready: bool = True,
    canary_promotable: bool = False,
) -> DogfoodReadiness:
    return DogfoodReadiness(
        ready=ready,
        canary_promotable=canary_promotable,
        blockers=(),
        warnings=(),
        local_main_sha="main-sha",
        origin_main_sha="main-sha",
        physical_worktree_count=1,
        canonical_worktree_present=True,
        metrics=metrics,
        cadence=cadence or MergeCadence(900, 0, 0.0, None, None, None),
        profile=DogfoodProfile(),
        backlog_drained=metrics.backlog_drained,
        pipeline_ready=metrics.pipeline_ready,
        ramp_ready=metrics.ramp_ready,
    )


def test_phase_mode_cli_is_explicit_and_parseable() -> None:
    args = _parser().parse_args(["dogfood-preflight", "--mode", "pilot"])

    assert args.mode == "pilot"


def test_pilot_allows_raw_backlog_and_reports_independent_lane_work() -> None:
    metrics = _metrics(
        active_development=1,
        raw_open_issues=5,
        unadmitted_open_issues=4,
        open_prs=1,
    )

    readiness = assess_phase_readiness(_base(metrics), mode=DogfoodMode.PILOT)

    assert readiness.ready is True
    assert readiness.pilot_ready is True
    assert readiness.backlog_classified is True
    assert readiness.backlog_drained is False
    assert readiness.global_freeze is False
    assert "triage_existing_issues" in readiness.next_actions
    assert "dispatch_solvers" in readiness.next_actions
    assert "healthy" not in readiness.next_actions


def test_pilot_without_candidate_is_supply_blocked_not_healthy() -> None:
    metrics = _metrics(
        candidate_issues=0,
        dispatchable_candidate_issues=0,
        raw_open_issues=5,
        unadmitted_open_issues=5,
    )

    readiness = assess_phase_readiness(_base(metrics), mode="pilot")

    assert readiness.ready is False
    assert readiness.pilot_ready is False
    assert readiness.next_actions == (
        "triage_existing_issues",
        "replenish_candidates",
    )
    assert "healthy" not in readiness.next_actions


def test_global_source_uncertainty_freezes_pilot() -> None:
    metrics = _metrics(
        source_problems=1,
        actionable_source_problems=1,
        actionable_global_source_problems=1,
        source_problem_scope_counts=(("global", 1),),
    )

    readiness = assess_phase_readiness(_base(metrics), mode=DogfoodMode.PILOT)

    assert readiness.ready is False
    assert readiness.global_freeze is True
    assert "delivery source inventory is incomplete" in readiness.global_blockers


def test_ramp_requires_pilot_promotion_proof_not_drained_backlog() -> None:
    metrics = _metrics(raw_open_issues=5, unadmitted_open_issues=4)
    cadence = MergeCadence(900, 3, 12.0, 300.0, 300.0, 60.0)

    readiness = assess_phase_readiness(
        _base(metrics, cadence=cadence, canary_promotable=True),
        mode="ramp",
    )

    assert readiness.pilot_ready is True
    assert readiness.backlog_drained is False
    assert readiness.ramp_ready is True
    assert readiness.ready is True


def test_steady_requires_one_hour_throughput_and_transport_slos() -> None:
    metrics = _metrics(
        raw_open_issues=5,
        unadmitted_open_issues=4,
        timings=PipelineTimings(
            window_seconds=3600,
            handback_to_pr_samples=12,
            handback_to_pr_p95_seconds=60.0,
            pr_to_required_start_samples=12,
            pr_to_required_start_p95_seconds=60.0,
            required_duration_samples=12,
            required_duration_p95_seconds=240.0,
            required_success_to_enqueue_samples=12,
            required_success_to_enqueue_p95_seconds=30.0,
            merge_to_sync_samples=12,
            merge_to_sync_p95_seconds=30.0,
            merge_to_cleanup_samples=12,
            merge_to_cleanup_p95_seconds=60.0,
        ),
    )
    cadence = MergeCadence(3600, 12, 12.0, 300.0, 300.0, 120.0)

    readiness = assess_phase_readiness(_base(metrics, cadence=cadence), mode="steady")

    assert readiness.steady_state_verified is True
    assert readiness.ready is True
    assert readiness.backlog_drained is False


def test_explicit_qualification_preserves_legacy_readiness() -> None:
    metrics = _metrics()
    base = _base(metrics, ready=False)
    base = replace(base, blockers=("legacy blocker",))

    readiness = assess_phase_readiness(base, mode="qualification")

    assert readiness.ready is False
    assert readiness.blockers == ("legacy blocker",)
    assert readiness.global_blockers == ("legacy blocker",)


def test_phase_result_is_additive_json_and_observation_not_authorization() -> None:
    readiness = assess_phase_readiness(_base(_metrics()), mode="pilot")
    payload = _jsonable(readiness)

    assert isinstance(payload, dict)
    assert payload["schema"] == "kg.delivery.dogfood-readiness.v2"
    assert payload["dispatch_authorized"] is False
    assert payload["mode"] == "pilot"


@pytest.mark.parametrize("mode", ("qualification", "pilot", "ramp", "steady"))
def test_all_phase_names_are_stable(mode: str) -> None:
    readiness = assess_phase_readiness(_base(_metrics()), mode=mode)

    assert readiness.mode == mode
