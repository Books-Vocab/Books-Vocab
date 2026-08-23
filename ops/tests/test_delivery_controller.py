from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

# The test imports the in-repository package after extending sys.path so it can
# run from the repository's ops test harness.
# ruff: noqa: E402
OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.controller.capacity import (
    DEFAULT_CAPACITY_POLICY,
    ControlAction,
    decide_capacity,
)
from delivery_control.controller.dogfood import DogfoodProfile, assess_dogfood_readiness
from delivery_control.controller.metrics import (
    PipelineMetrics,
    measure_merge_cadence,
    measure_pipeline,
)
from delivery_control.controller.timings import PipelineTimings
from delivery_control.controller.worktree_boundary import partition_worktrees
from delivery_control.domain.candidate_issues import (
    CandidateIssue,
    CandidateIssueInventory,
    CandidateSeverity,
    CandidateSpec,
    unclaimed_candidate_issues,
)
from delivery_control.domain.isolation import IsolationSummary
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.domain.states import (
    LaneDecision,
    LaneFacts,
    LaneState,
    NextAction,
    derive_lane_decision,
)
from delivery_control.services.inspect import DeliveryInventory, LaneInspection


def _metrics(**changes: int) -> PipelineMetrics:
    values = {
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
        "physical_worktrees": 0,
        "source_problems": 0,
        "candidate_issues": 30,
        "reanchor_required": 0,
        "clean_unregistered_worktrees": 0,
        "security_hold_lanes": 0,
        "security_hold_issues": 0,
    }
    values.update(changes)
    return PipelineMetrics(**values)


def _candidate(number: int) -> CandidateIssue:
    return CandidateIssue(
        number,
        f"https://github.com/owner/repo/issues/{number}",
        CandidateSpec(
            CandidateSeverity.P2,
            number,
            Scope.from_paths(modify=(f"ops/issue_{number}.py",)),
            (f"Issue {number} is fixed.",),
        ),
    )


def test_merge_cadence_measures_hourly_rate_and_nearest_rank_p95() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    merged = tuple(now - timedelta(minutes=offset) for offset in (25, 20, 15, 10, 5))

    cadence = measure_merge_cadence(merged, now=now)

    assert cadence.merged_count == 5
    assert cadence.merges_per_hour == 5.0
    assert cadence.p50_interval_seconds == 300.0
    assert cadence.p95_interval_seconds == 300.0
    assert cadence.seconds_since_last_merge == 300.0


def test_candidate_occupancy_accepts_issue_number_and_exact_url_forms() -> None:
    candidates = tuple(_candidate(number) for number in range(7, 11))

    unclaimed = unclaimed_candidate_issues(
        candidates,
        external_ids=(
            "#7",
            "8",
            "Issue-9",
            "https://github.com/owner/repo/issues/10/",
            "https://github.com/other/repo/issues/8",
        ),
    )

    assert unclaimed == ()


def test_candidate_occupancy_does_not_match_other_repository_issue_url() -> None:
    candidate = _candidate(8)

    assert unclaimed_candidate_issues(
        (candidate,),
        external_ids=("https://github.com/other/repo/issues/8",),
    ) == (candidate,)


def test_candidate_inventory_orders_dispatch_by_severity_then_priority() -> None:
    low = _candidate(8)
    urgent = replace(
        _candidate(9),
        spec=replace(_candidate(9).spec, severity=CandidateSeverity.P0, priority=50),
    )
    high_priority = _candidate(10)
    high_priority = replace(
        high_priority,
        spec=replace(high_priority.spec, priority=1),
    )

    inventory = CandidateIssueInventory((low, urgent, high_priority))

    assert [item.number for item in inventory.records] == [9, 10, 8]
    assert inventory.records[1].spec.priority == 1


def test_controller_drains_every_existing_reservoir_without_serializing() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            handbacks_publishable=2,
            published_local_cleanup=1,
            required_green=1,
            required_failed=1,
            pr_contract_failed=1,
            terminal_cleanup=1,
            blocked_lanes=1,
        ),
        cadence,
    )

    assert ControlAction.PUBLISH_HANDBACKS in decision.actions
    assert ControlAction.CLEANUP_LOCAL in decision.actions
    assert ControlAction.ENQUEUE_GREEN in decision.actions
    assert ControlAction.REPAIR_REQUIRED in decision.actions
    assert ControlAction.REPAIR_PR_CONTRACT in decision.actions
    assert ControlAction.CLEANUP_TERMINAL in decision.actions
    assert ControlAction.RECOVER_BLOCKERS in decision.actions
    assert decision.desired_new_solvers == 4


def test_transport_slo_breach_is_not_a_publish_command_without_handbacks() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            handbacks_publishable=0,
            timings=PipelineTimings(
                handback_to_pr_samples=3,
                handback_to_pr_p95_seconds=186.0,
            ),
        ),
        cadence,
    )

    assert ControlAction.PUBLISH_HANDBACKS not in decision.actions
    assert ControlAction.AUDIT_TRANSPORT_SLO in decision.actions


def test_transport_slo_breach_keeps_publish_command_for_real_handbacks() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            handbacks_publishable=1,
            timings=PipelineTimings(
                handback_to_pr_samples=3,
                handback_to_pr_p95_seconds=186.0,
            ),
        ),
        cadence,
    )

    assert ControlAction.PUBLISH_HANDBACKS in decision.actions
    assert ControlAction.AUDIT_TRANSPORT_SLO in decision.actions


def test_transport_slo_without_breach_does_not_create_transport_actions() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            handbacks_publishable=0,
            timings=PipelineTimings(
                handback_to_pr_samples=3,
                handback_to_pr_p95_seconds=45.0,
            ),
        ),
        cadence,
    )

    assert ControlAction.PUBLISH_HANDBACKS not in decision.actions
    assert ControlAction.AUDIT_TRANSPORT_SLO not in decision.actions


def test_quarantined_residue_has_observation_action_without_blocking_solver_supply() -> (
    None
):
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            quarantined_source_problems=2,
            quarantined_blocked_lanes=3,
            quarantined_open_prs=1,
            quarantined_terminal_cleanup=4,
        ),
        cadence,
    )

    assert ControlAction.AUDIT_QUARANTINE in decision.actions
    assert ControlAction.INSPECT_SOURCES not in decision.actions
    assert ControlAction.THROTTLE_SOLVERS not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions


def test_quarantine_observation_is_absent_without_quarantined_residue() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(_metrics(), cadence)

    assert ControlAction.AUDIT_QUARANTINE not in decision.actions


def test_recent_merges_without_sync_telemetry_have_observation_action() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    cadence = measure_merge_cadence(
        (now - timedelta(seconds=90), now - timedelta(seconds=30)), now=now
    )
    decision = decide_capacity(
        _metrics(timings=PipelineTimings(merge_to_sync_samples=0)), cadence
    )

    assert ControlAction.AUDIT_SYNC_TELEMETRY in decision.actions
    assert ControlAction.THROTTLE_SOLVERS not in decision.actions


def test_sync_telemetry_observation_clears_when_each_recent_merge_is_sampled() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    cadence = measure_merge_cadence(
        (now - timedelta(seconds=90), now - timedelta(seconds=30)), now=now
    )
    decision = decide_capacity(
        _metrics(timings=PipelineTimings(merge_to_sync_samples=2)), cadence
    )

    assert ControlAction.AUDIT_SYNC_TELEMETRY not in decision.actions


def test_sync_telemetry_observation_is_absent_without_recent_merges() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, 12, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(timings=PipelineTimings(merge_to_sync_samples=0)), cadence
    )

    assert ControlAction.AUDIT_SYNC_TELEMETRY not in decision.actions


def test_ci_start_slo_breach_is_not_a_required_repair_without_failed_checks() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            required_failed=0,
            required_absent=0,
            timings=PipelineTimings(pr_to_required_start_p95_seconds=61.0),
        ),
        cadence,
    )

    assert ControlAction.REPAIR_REQUIRED not in decision.actions
    assert ControlAction.AUDIT_CI_START_SLO in decision.actions


def test_ci_start_slo_breach_preserves_required_repair_for_failed_checks() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            required_failed=1,
            timings=PipelineTimings(pr_to_required_start_p95_seconds=61.0),
        ),
        cadence,
    )

    assert ControlAction.REPAIR_REQUIRED in decision.actions
    assert ControlAction.AUDIT_CI_START_SLO in decision.actions


def test_queue_admission_slo_breach_is_not_enqueue_without_green_work() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            required_green=0,
            timings=PipelineTimings(required_success_to_enqueue_p95_seconds=31.0),
        ),
        cadence,
    )

    assert ControlAction.ENQUEUE_GREEN not in decision.actions
    assert ControlAction.AUDIT_QUEUE_ADMISSION_SLO in decision.actions


def test_queue_admission_slo_breach_preserves_enqueue_for_green_work() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            required_green=1,
            timings=PipelineTimings(required_success_to_enqueue_p95_seconds=31.0),
        ),
        cadence,
    )

    assert ControlAction.ENQUEUE_GREEN in decision.actions
    assert ControlAction.AUDIT_QUEUE_ADMISSION_SLO in decision.actions


def test_candidate_policy_replenishes_low_reservoir_while_dispatching_existing_supply() -> (
    None
):
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    decision = decide_capacity(_metrics(candidate_issues=2), cadence)

    assert DEFAULT_CAPACITY_POLICY.min_candidate_issues == 20
    assert DEFAULT_CAPACITY_POLICY.max_candidate_issues == 30
    assert ControlAction.REPLENISH_CANDIDATES in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions
    assert decision.desired_new_solvers == 2


def test_candidate_policy_never_dispatches_more_solvers_than_unclaimed_candidates() -> (
    None
):
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    decision = decide_capacity(_metrics(candidate_issues=0), cadence)

    assert ControlAction.REPLENISH_CANDIDATES in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0


def test_pipeline_metrics_excludes_explicit_supervision_worktrees() -> None:
    path = Path("/supervision/one")
    lane = LaneInspection(
        key=str(path),
        registry=None,
        physical=PhysicalWorktree(path, "b" * 40, None),
        snapshot=WorktreeSnapshot(
            path=path,
            branch=None,
            base_sha="a" * 40,
            head_sha="b" * 40,
            parent_sha="a" * 40,
            clean=True,
            changes=(),
        ),
        pull_requests=(),
        decision=derive_lane_decision(LaneFacts(has_worktree=True)),
    )
    inventory = DeliveryInventory(lanes=(lane,))

    measured = measure_pipeline(
        inventory,
        excluded_worktree_paths=(path,),
    )

    assert measured.physical_worktrees == 0
    assert measured.clean_unregistered_worktrees == 0
    assert measured.idle_worktrees == 0
    assert measured.blocked_lanes == 0


def test_quarantined_open_prs_do_not_count_as_actionable_blockers() -> None:
    lanes = tuple(
        LaneInspection(
            key=f"PR#{number}",
            registry=None,
            physical=None,
            snapshot=None,
            pull_requests=(
                PullRequestSnapshot(
                    number=number,
                    url=f"https://example.test/pull/{number}",
                    branch=f"legacy/{number}",
                    base_sha="a" * 40,
                    head_sha="b" * 40,
                    state="OPEN",
                    draft=False,
                    mergeable=True,
                ),
            ),
            decision=LaneDecision(
                LaneState.UNKNOWN,
                NextAction.INSPECT,
                "preserved legacy PR",
            ),
        )
        for number in (1376, 1422)
    )
    measured = measure_pipeline(
        DeliveryInventory(
            lanes=lanes,
            isolation=IsolationSummary(quarantined_open_prs=2),
        )
    )

    assert measured.blocked_lanes == 2
    assert measured.quarantined_open_prs == 2
    assert measured.actionable_blocked_lanes == 0


def test_controller_triggers_missing_required_without_overproducing_solvers() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    decision = decide_capacity(
        _metrics(required_absent=2, active_development=12), cadence
    )

    assert ControlAction.TRIGGER_REQUIRED in decision.actions
    assert ControlAction.THROTTLE_SOLVERS in decision.actions
    assert decision.desired_new_solvers == 0


def test_controller_requests_scope_repartition_under_collision_pressure() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    decision = decide_capacity(
        replace(_metrics(blocked_lanes=3), collision_rate=0.21),
        cadence,
    )

    assert DEFAULT_CAPACITY_POLICY.max_collision_pressure == 0.20
    assert ControlAction.RECOVER_BLOCKERS in decision.actions
    assert ControlAction.IMPROVE_SCOPE_PARTITION in decision.actions
    assert ControlAction.THROTTLE_SOLVERS in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0


def test_solver_birth_respects_active_wip_ceiling() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    decision = decide_capacity(
        _metrics(candidate_issues=30, active_development=7),
        cadence,
        policy=replace(DEFAULT_CAPACITY_POLICY, min_open_prs=15),
    )

    assert DEFAULT_CAPACITY_POLICY.target_active_solvers == 8
    assert DEFAULT_CAPACITY_POLICY.max_active_solvers == 12
    assert decision.desired_new_solvers == 1

    above_target = decide_capacity(
        _metrics(candidate_issues=30, active_development=11), cadence
    )
    assert above_target.desired_new_solvers == 0


def test_controller_keeps_solver_band_while_pr_reservoir_drains() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    first_cycle = decide_capacity(
        _metrics(candidate_issues=30, open_prs=10, active_development=0),
        cadence,
    )
    second_cycle = decide_capacity(
        _metrics(candidate_issues=26, open_prs=10, active_development=4),
        cadence,
    )

    assert first_cycle.desired_new_solvers == 4
    assert second_cycle.desired_new_solvers == 4
    assert ControlAction.DISPATCH_SOLVERS in first_cycle.actions
    assert ControlAction.DISPATCH_SOLVERS in second_cycle.actions


def test_controller_keeps_solver_band_before_cadence_degrades() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    healthy_cadence = measure_merge_cadence(
        tuple(now - timedelta(minutes=5 * offset) for offset in range(12)),
        now=now,
    )

    decision = decide_capacity(
        _metrics(candidate_issues=30, open_prs=10, active_development=4),
        healthy_cadence,
    )

    assert healthy_cadence.merges_per_hour == 12.0
    assert decision.desired_new_solvers == 4
    assert ControlAction.DISPATCH_SOLVERS in decision.actions


def test_controller_never_reports_healthy_when_merge_cadence_misses_slo() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    stalled = measure_merge_cadence((), now=now)
    metrics = _metrics(
        active_development=8,
        open_prs=10,
        required_running=3,
        merge_queue_depth=3,
    )

    decision = decide_capacity(metrics, stalled)

    assert ControlAction.AUDIT_MERGE_CADENCE in decision.actions
    assert ControlAction.RECOVER_MERGE_CADENCE in decision.actions
    assert ControlAction.HEALTHY not in decision.actions


def test_controller_audits_cadence_without_claiming_recovery_supply() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    stalled = measure_merge_cadence((), now=now)

    decision = decide_capacity(_metrics(), stalled)

    assert ControlAction.AUDIT_MERGE_CADENCE in decision.actions
    assert ControlAction.RECOVER_MERGE_CADENCE not in decision.actions


def test_controller_does_not_audit_cadence_when_slo_is_healthy() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    healthy = measure_merge_cadence(
        tuple(now - timedelta(minutes=5 * offset) for offset in range(12)),
        now=now,
    )

    decision = decide_capacity(_metrics(candidate_issues=0), healthy)

    assert ControlAction.AUDIT_MERGE_CADENCE not in decision.actions
    assert ControlAction.RECOVER_MERGE_CADENCE not in decision.actions


def test_controller_requires_required_and_merge_buffer_watermarks() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    healthy_cadence = measure_merge_cadence(
        tuple(now - timedelta(minutes=5 * offset) for offset in range(12)),
        now=now,
    )

    decision = decide_capacity(
        _metrics(
            active_development=8,
            open_prs=10,
            required_running=1,
            required_green=1,
            merge_queue_depth=1,
        ),
        healthy_cadence,
    )

    assert ControlAction.FILL_REQUIRED_CAPACITY in decision.actions
    assert ControlAction.RESTORE_MERGE_BUFFER in decision.actions
    assert ControlAction.HEALTHY not in decision.actions


def test_controller_reports_healthy_only_with_cadence_and_capacity_watermarks() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    healthy_cadence = measure_merge_cadence(
        tuple(now - timedelta(minutes=5 * offset) for offset in range(12)),
        now=now,
    )

    decision = decide_capacity(
        _metrics(
            active_development=8,
            open_prs=10,
            required_running=3,
            merge_queue_depth=3,
            timings=PipelineTimings(merge_to_sync_samples=12),
        ),
        healthy_cadence,
    )

    assert decision.actions == (ControlAction.HEALTHY,)


def test_controller_stops_solver_birth_at_pr_ceiling_even_below_solver_target() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    decision = decide_capacity(
        _metrics(
            candidate_issues=30,
            open_prs=DEFAULT_CAPACITY_POLICY.max_open_prs,
            active_development=2,
        ),
        cadence,
    )

    assert ControlAction.THROTTLE_SOLVERS in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0


def test_reanchor_lane_is_measured_and_moved_to_merge_front() -> None:
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key="published:#1",
                registry=None,
                physical=None,
                snapshot=None,
                pull_requests=(),
                decision=LaneDecision(
                    LaneState.REANCHOR,
                    NextAction.REANCHOR,
                    "live base advanced",
                ),
            ),
        ),
        candidate_issues=(_candidate(1),),
    )

    metrics = measure_pipeline(inventory)
    decision = decide_capacity(
        metrics,
        measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC)),
    )

    assert metrics.reanchor_required == 1
    assert metrics.candidate_issues == 1
    assert ControlAction.REANCHOR_FRONT in decision.actions


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


def test_controller_consumes_observed_required_p95_without_manual_injection() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    metrics = replace(
        _metrics(active_development=1, open_prs=3),
        timings=PipelineTimings(required_duration_p95_seconds=500),
    )

    decision = decide_capacity(metrics, cadence)

    assert ControlAction.THROTTLE_SOLVERS in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions


def test_controller_turns_transport_and_admission_latency_into_actions() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    metrics = replace(
        _metrics(open_prs=10),
        timings=PipelineTimings(
            handback_to_pr_p95_seconds=61,
            pr_to_required_start_p95_seconds=61,
            required_success_to_enqueue_p95_seconds=31,
        ),
    )

    decision = decide_capacity(metrics, cadence)

    assert ControlAction.AUDIT_TRANSPORT_SLO in decision.actions
    assert ControlAction.PUBLISH_HANDBACKS not in decision.actions
    assert ControlAction.AUDIT_CI_START_SLO in decision.actions
    assert ControlAction.AUDIT_QUEUE_ADMISSION_SLO in decision.actions
    assert ControlAction.REPAIR_REQUIRED not in decision.actions
    assert ControlAction.ENQUEUE_GREEN not in decision.actions


def test_controller_reports_source_uncertainty_instead_of_fabricating_supply() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(_metrics(source_problems=2), cadence)
    assert ControlAction.INSPECT_SOURCES in decision.actions
    assert ControlAction.RECOVER_BLOCKERS in decision.actions
    assert ControlAction.REPLENISH_CANDIDATES not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0


def test_hard_holds_block_ramp_and_solver_birth_until_reconciled() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    metrics = _metrics(security_hold_lanes=1, security_hold_issues=1)

    decision = decide_capacity(metrics, cadence)

    assert ControlAction.RECONCILE_HOLDS in decision.actions
    assert ControlAction.THROTTLE_SOLVERS in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0

    readiness = assess_dogfood_readiness(
        local_main_sha="a" * 40,
        origin_main_sha="a" * 40,
        canonical_branch="main",
        canonical_clean=True,
        main_protected=True,
        required_status_contexts=("required",),
        merge_queue_enabled=True,
        physical_worktree_count=1,
        canonical_worktree_present=True,
        metrics=metrics,
        cadence=cadence,
    )

    assert readiness.ready is False
    assert (
        "explicit P0/P1/security holds require terminal disposition"
        in readiness.blockers
    )


def test_controller_disables_solver_birth_for_unmapped_or_duplicate_prs() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    for metrics in (
        _metrics(unmapped_open_prs=1),
        _metrics(duplicate_pr_mappings=1),
    ):
        decision = decide_capacity(metrics, cadence)
        assert ControlAction.DISPATCH_SOLVERS not in decision.actions
        assert ControlAction.RECOVER_BLOCKERS in decision.actions
        assert decision.desired_new_solvers == 0


def test_dogfood_preflight_accepts_only_an_empty_canonical_baseline() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    cadence = measure_merge_cadence((), now=now)

    readiness = assess_dogfood_readiness(
        local_main_sha="a" * 40,
        origin_main_sha="a" * 40,
        canonical_branch="main",
        canonical_clean=True,
        main_protected=True,
        required_status_contexts=("required",),
        merge_queue_enabled=True,
        physical_worktree_count=1,
        canonical_worktree_present=True,
        metrics=_metrics(candidate_issues=0),
        cadence=cadence,
    )

    assert readiness.ready
    assert readiness.blockers == ()
    assert readiness.profile.roles == ("backlog_scout", "pi", "cm", "supervisor")
    assert readiness.profile.canary_solver_limit == 1
    assert readiness.profile.target_inter_merge_seconds == 300
    assert readiness.profile.watchdog_tick_seconds == 300
    assert readiness.canary_promotable is False


def test_worktree_boundary_requires_explicit_supervision_manifest() -> None:
    canonical = Path("/repo")
    supervision = tuple(
        PhysicalWorktree(Path(f"/supervision/{index}"), "b" * 40, None)
        for index in range(4)
    )
    partition = partition_worktrees(
        (PhysicalWorktree(canonical, "a" * 40, "main"), *supervision),
        canonical_path=canonical,
        supervision_paths=tuple(item.path for item in supervision),
    )

    assert len(partition.delivery) == 1
    assert len(partition.supervision) == 4
    assert partition.canonical_count == 1

    unknown = partition_worktrees(
        (
            PhysicalWorktree(canonical, "a" * 40, "main"),
            *supervision,
            PhysicalWorktree(Path("/unknown/product"), "c" * 40, "feat/unknown"),
        ),
        canonical_path=canonical,
        supervision_paths=tuple(item.path for item in supervision),
    )
    assert len(unknown.delivery) == 2


def test_dogfood_canary_promotion_uses_exact_fifteen_minute_cadence() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    cadence = measure_merge_cadence(
        (
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            now,
        ),
        now=now,
        window=timedelta(minutes=15),
    )

    readiness = assess_dogfood_readiness(
        local_main_sha="a" * 40,
        origin_main_sha="a" * 40,
        canonical_branch="main",
        canonical_clean=True,
        main_protected=True,
        required_status_contexts=("required",),
        merge_queue_enabled=True,
        physical_worktree_count=1,
        canonical_worktree_present=True,
        metrics=_metrics(candidate_issues=0),
        cadence=cadence,
    )

    assert readiness.canary_promotable is True
    assert readiness.warnings == ()


def test_dogfood_canary_rejects_wrong_window_or_slow_intermerge() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    hourly = measure_merge_cadence(
        tuple(now - timedelta(minutes=5 * offset) for offset in range(3)),
        now=now,
    )
    slow = measure_merge_cadence(
        (
            now - timedelta(minutes=14),
            now - timedelta(minutes=8),
            now,
        ),
        now=now,
        window=timedelta(minutes=15),
    )

    common = {
        "local_main_sha": "a" * 40,
        "origin_main_sha": "a" * 40,
        "canonical_branch": "main",
        "canonical_clean": True,
        "main_protected": True,
        "required_status_contexts": ("required",),
        "merge_queue_enabled": True,
        "physical_worktree_count": 1,
        "canonical_worktree_present": True,
        "metrics": _metrics(candidate_issues=0),
    }

    assert assess_dogfood_readiness(cadence=hourly, **common).canary_promotable is False
    assert assess_dogfood_readiness(cadence=slow, **common).canary_promotable is False


def test_dogfood_canary_uses_custom_promotion_window_and_interval_policy() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    profile = DogfoodProfile(
        promotion_merge_count=2,
        promotion_observation_seconds=600,
        target_inter_merge_seconds=120,
    )
    cadence = measure_merge_cadence(
        (now - timedelta(minutes=2), now),
        now=now,
        window=timedelta(minutes=10),
    )

    readiness = assess_dogfood_readiness(
        local_main_sha="a" * 40,
        origin_main_sha="a" * 40,
        canonical_branch="main",
        canonical_clean=True,
        main_protected=True,
        required_status_contexts=("required",),
        merge_queue_enabled=True,
        physical_worktree_count=1,
        canonical_worktree_present=True,
        metrics=_metrics(candidate_issues=0),
        cadence=cadence,
        profile=profile,
    )

    assert readiness.canary_promotable is True
    assert readiness.warnings == ()


def test_dogfood_preflight_blocks_debt_drift_and_missing_queue() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    readiness = assess_dogfood_readiness(
        local_main_sha="a" * 40,
        origin_main_sha="b" * 40,
        canonical_branch="feat/not-main",
        canonical_clean=False,
        main_protected=False,
        required_status_contexts=(),
        merge_queue_enabled=False,
        physical_worktree_count=2,
        canonical_worktree_present=True,
        metrics=_metrics(
            source_problems=2,
            blocked_lanes=1,
            unmapped_open_prs=1,
            pr_contract_failed=1,
        ),
        cadence=cadence,
    )

    assert not readiness.ready
    assert "local main differs from origin/main" in readiness.blockers
    assert "main is not protected" in readiness.blockers
    assert "main does not require the short required context" in readiness.blockers
    assert "delivery source inventory is incomplete" in readiness.blockers
    assert "main has no native merge queue rule" in readiness.blockers
    assert "existing PR delivery contracts are invalid" in readiness.blockers


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


def test_idle_worktrees_include_clean_unregistered_physical_checkout() -> None:
    path = Path("/tmp/unregistered-clean")
    physical = PhysicalWorktree(path=path, head_sha="b" * 40, branch="feat/clean")
    snapshot = WorktreeSnapshot(
        path=path,
        branch="feat/clean",
        base_sha="a" * 40,
        head_sha="b" * 40,
        parent_sha="a" * 40,
        clean=True,
        changes=(),
    )
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key=str(path),
                registry=None,
                physical=physical,
                snapshot=snapshot,
                pull_requests=(),
                decision=LaneDecision(
                    LaneState.BLOCKED_OWNER,
                    NextAction.RECOVER_OWNER,
                    "unregistered",
                ),
            ),
        )
    )

    metrics = measure_pipeline(inventory)

    assert metrics.idle_worktrees == 1
    assert metrics.source_problems == 0


def test_metrics_exposes_active_registry_residue_separately_from_development() -> None:
    active_record = RegistrySnapshot(
        lane_id="#active",
        branch="debug/active",
        path=Path("/tmp/active"),
        status="active",
        scope=Scope.from_paths(modify=("ops/active.py",)),
        base_sha="a" * 40,
        claim_generation=1,
    )
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key="#active",
                registry=active_record,
                physical=None,
                snapshot=None,
                pull_requests=(),
                decision=LaneDecision(
                    LaneState.BLOCKED_OWNER,
                    NextAction.RECOVER_OWNER,
                    "owner unavailable",
                ),
            ),
        ),
        source_problems=(
            InventoryProblem(
                "registry",
                "debug/malformed-active",
                "claim_generation must be a non-negative integer",
                identity_kind="branch",
                record_status="active",
            ),
        ),
    )

    metrics = measure_pipeline(inventory)

    assert metrics.active_development == 0
    assert metrics.active_registry_records == 1
    assert metrics.raw_active_registry_records == 2
    assert metrics.active_registry_without_worktree == 1
    assert metrics.malformed_active_registry_records == 1


def test_unknown_unregistered_worktree_cleanliness_is_a_source_problem() -> None:
    path = Path("/tmp/unregistered-unknown")
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key=str(path),
                registry=None,
                physical=PhysicalWorktree(
                    path=path,
                    head_sha="b" * 40,
                    branch="feat/unknown",
                ),
                snapshot=None,
                pull_requests=(),
                decision=LaneDecision(
                    LaneState.UNKNOWN,
                    NextAction.INSPECT,
                    "uninspectable",
                ),
            ),
        )
    )

    metrics = measure_pipeline(inventory)
    decision = decide_capacity(
        metrics,
        measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC)),
    )

    assert metrics.idle_worktrees == 0
    assert metrics.source_problems == 1
    assert ControlAction.INSPECT_SOURCES in decision.actions


def test_cleanup_pending_pr_counts_as_durable_mapped_supply() -> None:
    pull_request = PullRequestSnapshot(
        number=9,
        url="https://example.test/pull/9",
        branch="feat/leased",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
    )
    record = RegistrySnapshot(
        lane_id="#leased",
        branch="feat/leased",
        path=Path("/tmp/leased"),
        status="cleanup_pending",
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha="a" * 40,
        claim_generation=1,
    )
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key="#leased",
                registry=record,
                physical=None,
                snapshot=None,
                pull_requests=(pull_request,),
                decision=LaneDecision(
                    LaneState.PUBLISHED_LOCAL_CLEANUP,
                    NextAction.CLEANUP_LOCAL,
                    "cleanup",
                ),
            ),
        )
    )

    metrics = measure_pipeline(inventory)

    assert metrics.open_prs == 1
    assert metrics.unmapped_open_prs == 0
    assert metrics.cleanup_pending == 1

    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(metrics, cadence)

    assert ControlAction.CLEANUP_LOCAL in decision.actions
    assert ControlAction.THROTTLE_SOLVERS in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0
