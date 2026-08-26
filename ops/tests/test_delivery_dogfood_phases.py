# ruff: noqa: E402

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# The test imports the in-repository package after extending sys.path so it can
# run from the repository's ops test harness.
OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.cli import _jsonable, _parser, run_command
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


def test_pilot_accepts_an_explicit_direct_assignment_without_candidate() -> None:
    metrics = _metrics(
        candidate_issues=0,
        dispatchable_candidate_issues=0,
        raw_open_issues=54,
        unadmitted_open_issues=54,
    )

    readiness = assess_phase_readiness(
        _base(metrics),
        mode="pilot",
        direct_assignment_available=True,
    )

    assert readiness.ready is True
    assert readiness.pilot_ready is True
    assert readiness.direct_assignment_available is True
    assert readiness.dispatchable_candidate_issues == 0
    assert "triage_existing_issues" in readiness.next_actions


def test_pilot_keeps_existing_reservoir_and_known_worktrees_observational() -> None:
    metrics = _metrics(
        active_development=2,
        open_prs=10,
        handbacks_publishable=1,
        published_local_cleanup=1,
    )
    base = replace(
        _base(metrics),
        blockers=(
            "pre-dogfood development lanes remain",
            "pre-dogfood handbacks remain local",
            "owner-mapped PR reservoir is not empty",
            "physical worktree baseline is not canonical-main only",
        ),
    )

    readiness = assess_phase_readiness(base, mode="pilot")

    assert readiness.ready is True
    assert readiness.global_freeze is False
    assert "pre-dogfood development lanes remain" not in readiness.lane_blockers
    assert "pre-dogfood handbacks remain local" not in readiness.lane_blockers
    assert "owner-mapped PR reservoir is not empty" not in readiness.lane_blockers
    assert (
        "physical worktree baseline is not canonical-main only"
        not in readiness.lane_blockers
    )
    assert (
        "durable PR reservoir remains (10); it is not a global freeze"
        in readiness.warnings
    )


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


def test_global_freeze_suppresses_dispatch_and_replenishment_actions() -> None:
    metrics = _metrics(
        candidate_issues=5,
        dispatchable_candidate_issues=5,
        source_problems=1,
        actionable_source_problems=1,
        actionable_global_source_problems=1,
        source_problem_scope_counts=(("global", 1),),
    )

    readiness = assess_phase_readiness(_base(metrics), mode="pilot")

    assert readiness.global_freeze is True
    assert "dispatch_solvers" not in readiness.next_actions
    assert "replenish_candidates" not in readiness.next_actions


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
        active_development=8,
        open_prs=10,
        candidate_issues=20,
        dispatchable_candidate_issues=20,
        required_green=3,
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


def test_steady_requires_the_target_reservoir_bands() -> None:
    metrics = _metrics(
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
        )
    )
    cadence = MergeCadence(3600, 12, 12.0, 300.0, 300.0, 120.0)

    readiness = assess_phase_readiness(_base(metrics, cadence=cadence), mode="steady")

    assert readiness.steady_state_verified is False
    assert readiness.ready is False


def test_explicit_qualification_preserves_legacy_readiness() -> None:
    metrics = _metrics()
    base = _base(metrics, ready=False)
    base = replace(base, blockers=("legacy blocker",))

    readiness = assess_phase_readiness(base, mode="qualification")

    assert readiness.ready is False
    assert readiness.blockers == ("legacy blocker",)
    assert readiness.global_blockers == ()
    assert readiness.lane_blockers == ("legacy blocker",)


def test_phase_result_is_additive_json_and_observation_not_authorization() -> None:
    readiness = assess_phase_readiness(_base(_metrics()), mode="pilot")
    payload = _jsonable(readiness)

    assert isinstance(payload, dict)
    assert payload["schema"] == "kg.delivery.dogfood-readiness.v2"
    assert payload["dispatch_authorized"] is False
    assert payload["direct_assignment_available"] is False
    assert payload["mode"] == "pilot"


def test_cli_projects_direct_assignment_as_observation_only() -> None:
    metrics = _metrics(
        candidate_issues=0,
        dispatchable_candidate_issues=0,
        raw_open_issues=54,
        unadmitted_open_issues=54,
    )

    class FakeApplication:
        def dogfood_preflight(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> DogfoodReadiness:
            assert supervision_worktree_paths == ()
            return _base(metrics)

    args = _parser().parse_args(
        ["dogfood-preflight", "--mode", "pilot", "--direct-assignment"]
    )
    result = run_command(args, FakeApplication())

    assert result.ready is True
    assert result.pilot_ready is True
    assert result.direct_assignment_available is True
    assert result.dispatch_authorized is False


def test_cli_projects_explicit_pilot_mode_without_granting_authority() -> None:
    metrics = _metrics(raw_open_issues=3, unadmitted_open_issues=2)

    class FakeApplication:
        def dogfood_preflight(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> DogfoodReadiness:
            assert supervision_worktree_paths == ()
            return _base(metrics)

    args = _parser().parse_args(["dogfood-preflight", "--mode", "pilot"])
    result = run_command(args, FakeApplication())

    assert result.mode == "pilot"
    assert result.ready is True
    assert result.dispatch_authorized is False


def test_cli_steady_mode_remeasures_an_exact_one_hour_window() -> None:
    fixed_now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    merged = tuple(fixed_now - timedelta(minutes=5 * index) for index in range(12))

    class FakeGitHub:
        def recent_merge_times(self) -> tuple[datetime, ...]:
            return merged

    class FakeApplication:
        github = FakeGitHub()

        def clock(self) -> datetime:
            return fixed_now

        def dogfood_preflight(
            self,
            *,
            now: datetime,
            supervision_worktree_paths: tuple[Path, ...],
        ) -> DogfoodReadiness:
            assert now == fixed_now
            assert supervision_worktree_paths == ()
            return _base(
                _metrics(), cadence=MergeCadence(900, 0, 0.0, None, None, None)
            )

    args = _parser().parse_args(["dogfood-preflight", "--mode", "steady"])
    result = run_command(args, FakeApplication())

    assert result.cadence.window_seconds == 3600
    assert result.cadence.merged_count == 12


def test_plan_exposes_phase_actions_without_replacing_capacity_decision() -> None:
    metrics = _metrics(
        raw_open_issues=4,
        unadmitted_open_issues=3,
        candidate_issues=2,
        dispatchable_candidate_issues=2,
    )

    class FakeApplication:
        def plan(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> dict[str, object]:
            assert supervision_worktree_paths == ()
            return {"metrics": metrics, "decision": "legacy-decision"}

    args = _parser().parse_args(["plan"])
    result = run_command(args, FakeApplication())

    assert result["decision"] == "legacy-decision"
    assert result["backlog_classified"] is True
    assert result["next_actions"] == (
        "triage_existing_issues",
        "dispatch_solvers",
        "replenish_candidates",
    )


def test_phase_actions_expose_existing_recovery_work() -> None:
    metrics = _metrics(
        reanchor_required=1,
        pr_contract_failed=1,
        required_failed=1,
        required_absent=1,
    )

    readiness = assess_phase_readiness(_base(metrics), mode="pilot")

    assert "reanchor_front" in readiness.next_actions
    assert "repair_pr_contract" in readiness.next_actions
    assert "repair_required" in readiness.next_actions
    assert "trigger_required" in readiness.next_actions


def test_lane_failure_does_not_become_global_freeze_for_pilot() -> None:
    metrics = _metrics(required_failed=1, open_prs=1)

    readiness = assess_phase_readiness(_base(metrics, ready=False), mode="pilot")

    assert readiness.ready is True
    assert readiness.global_freeze is False
    assert "existing required checks are failed" in readiness.lane_blockers


@pytest.mark.parametrize("mode", ("qualification", "pilot", "ramp", "steady"))
def test_all_phase_names_are_stable(mode: str) -> None:
    readiness = assess_phase_readiness(_base(_metrics()), mode=mode)

    assert readiness.mode == mode
