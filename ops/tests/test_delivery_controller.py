from __future__ import annotations

import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# The test imports the in-repository package after extending sys.path so it can
# run from the repository's ops test harness.
OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_parsing import parse_demand_issue
from delivery_control.controller.capacity import (
    DEFAULT_CAPACITY_POLICY,
    ControlAction,
    decide_capacity,
)
from delivery_control.controller.dogfood import DogfoodProfile, assess_dogfood_readiness
from delivery_control.controller.metrics import (
    MergeCadence,
    PipelineMetrics,
    measure_merge_cadence,
    measure_pipeline,
)
from delivery_control.controller.timings import PipelineTimings
from delivery_control.controller.worktree_boundary import partition_worktrees
from delivery_control.domain.branch_lifecycle import (
    BranchAsset,
    BranchCleanupAction,
    BranchDisposition,
    BranchLifecycleInventory,
    BranchSide,
)
from delivery_control.domain.candidate_issues import (
    CandidateIssue,
    CandidateIssueInventory,
    CandidateSeverity,
    CandidateSpec,
    unclaimed_candidate_issues,
)
from delivery_control.domain.demand_issues import DemandIssueInventory
from delivery_control.domain.isolation import IsolationSummary
from delivery_control.domain.models import CheckStatus, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
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
from delivery_control.services.demand_projection import project_demand_inventory
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
        "raw_open_issues": 0,
        "unadmitted_open_issues": 0,
        "issue_inventory_complete": True,
        "clean_unregistered_worktrees": 0,
        "security_hold_lanes": 0,
        "security_hold_issues": 0,
    }
    values.update(changes)
    return PipelineMetrics(**values)


def test_direct_metrics_without_issue_inventory_fail_closed() -> None:
    metrics = PipelineMetrics(
        active_development=0,
        handbacks_publishable=0,
        published_local_cleanup=0,
        cleanup_pending=0,
        open_prs=0,
        unmapped_open_prs=0,
        duplicate_pr_mappings=0,
        required_green=0,
        required_running=0,
        required_failed=0,
        required_absent=0,
        pr_contract_failed=0,
        merge_queue_depth=0,
        terminal_cleanup=0,
        blocked_lanes=0,
        physical_worktrees=0,
        source_problems=0,
        candidate_issues=30,
        reanchor_required=0,
    )
    decision = decide_capacity(
        metrics,
        MergeCadence(3600, 0, 0.0, None, None, None),
    )

    assert metrics.raw_open_issues is None
    assert metrics.unadmitted_open_issues is None
    assert metrics.issue_inventory_complete is False
    assert metrics.backlog_drained is False
    assert metrics.ramp_ready is False
    assert ControlAction.TRIAGE_EXISTING_ISSUES in decision.actions
    assert ControlAction.REPLENISH_CANDIDATES not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions


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


def _pull_request(state: str) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch="feat/required",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state=state,
        draft=False,
        mergeable=True,
    )


def _required_metrics_inventory(
    *,
    pull_requests: tuple[PullRequestSnapshot, ...],
    required_status: CheckStatus,
    registry_status: str = "published",
) -> DeliveryInventory:
    registry = RegistrySnapshot(
        lane_id="#required",
        branch="feat/required",
        path=Path("/tmp/required"),
        status=registry_status,
        scope=Scope.from_paths(modify=("ops/required.py",)),
        base_sha="a" * 40,
        claim_generation=1,
    )
    required_check = CheckSnapshot(
        status=required_status,
        head_sha="b" * 40,
        observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        names=() if required_status is CheckStatus.ABSENT else ("required",),
    )
    return DeliveryInventory(
        lanes=(
            LaneInspection(
                key="#required",
                registry=registry,
                physical=None,
                snapshot=None,
                pull_requests=pull_requests,
                decision=LaneDecision(
                    LaneState.PR_WAITING_REQUIRED,
                    NextAction.WAIT_REQUIRED,
                    "waiting for required",
                ),
                required_check=required_check,
            ),
        )
    )


@pytest.mark.parametrize(
    (
        "registry_status",
        "pull_request_state",
        "required_status",
        "expected_absent",
        "expected_running",
        "expected_failed",
    ),
    (
        ("published", None, CheckStatus.ABSENT, 0, 0, 0),
        ("published", "OPEN", CheckStatus.ABSENT, 1, 0, 0),
        ("cleanup_pending", "OPEN", CheckStatus.ABSENT, 1, 0, 0),
        ("published", "CLOSED", CheckStatus.ABSENT, 0, 0, 0),
        ("published", "OPEN", CheckStatus.SUCCESS, 0, 0, 0),
        ("published", "OPEN", CheckStatus.FAILURE, 0, 0, 1),
    ),
    ids=(
        "empty-absent",
        "published-open-absent",
        "cleanup-pending-open-absent",
        "closed-absent",
        "open-success",
        "open-failure",
    ),
)
def test_required_metrics_preserve_pr_and_check_status_semantics(
    registry_status: str,
    pull_request_state: str | None,
    required_status: CheckStatus,
    expected_absent: int,
    expected_running: int,
    expected_failed: int,
) -> None:
    metrics = measure_pipeline(
        _required_metrics_inventory(
            pull_requests=(
                ()
                if pull_request_state is None
                else (_pull_request(pull_request_state),)
            ),
            required_status=required_status,
            registry_status=registry_status,
        )
    )

    assert metrics.required_absent == expected_absent
    assert metrics.required_running == expected_running
    assert metrics.required_failed == expected_failed


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


def test_pipeline_metrics_preserves_inventory_main_baselines() -> None:
    inventory = DeliveryInventory(
        lanes=(),
        live_main_sha="a" * 40,
        local_main_sha="b" * 40,
    )

    measured = measure_pipeline(inventory)

    assert measured.live_main_sha == "a" * 40
    assert measured.local_main_sha == "b" * 40


def test_pipeline_metrics_exposes_branch_scoped_source_residue() -> None:
    measured = measure_pipeline(
        DeliveryInventory(
            lanes=(),
            source_problems=(
                InventoryProblem(
                    "registry",
                    "feat/legacy-residue",
                    "malformed record",
                    identity_kind="branch",
                ),
            ),
        )
    )

    assert measured.source_problem_scope_counts == (("branch", 1),)
    assert measured.actionable_source_problems == 1
    assert measured.actionable_global_source_problems == 0
    assert measured.pipeline_ready is False


def test_pipeline_metrics_direct_construction_keeps_legacy_optional_baselines() -> None:
    measured = _metrics()

    assert measured.live_main_sha is None
    assert measured.local_main_sha is None


def test_pipeline_metrics_projects_branch_lifecycle_residue() -> None:
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=BranchLifecycleInventory(
            assets=(
                BranchAsset(
                    branch="feat/local-orphan",
                    side=BranchSide.LOCAL,
                    sha="a" * 40,
                    disposition=BranchDisposition.ORPHAN_LOCAL_RECONCILE,
                    cleanup_action=BranchCleanupAction.RECONCILE_LOCAL_ORPHAN,
                    reason="local branch has no delivery evidence",
                ),
                BranchAsset(
                    branch="feat/remote-drift",
                    side=BranchSide.REMOTE,
                    sha="b" * 40,
                    disposition=BranchDisposition.REMOTE_DRIFT,
                    cleanup_action=BranchCleanupAction.PRESERVE_REMOTE_DRIFT,
                    reason="remote branch drifted from local evidence",
                ),
                BranchAsset(
                    branch="feat/protected",
                    side=BranchSide.LOCAL,
                    sha="c" * 40,
                    disposition=BranchDisposition.PROTECTED,
                    cleanup_action=BranchCleanupAction.PRESERVE_PROTECTED,
                    reason="protected branch",
                    protected=True,
                ),
            )
        ),
    )

    measured = measure_pipeline(inventory)

    assert measured.branch_audit_items == 2
    assert measured.local_orphan_branches == 1
    assert measured.remote_orphan_branches == 0
    assert measured.merged_branch_cleanup_ready == 0
    assert measured.remote_drift_branches == 1


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


def test_controller_explains_unadmitted_issue_dispositions() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            candidate_issues=0,
            unadmitted_open_issues=37,
            triage_required_issues=6,
            legacy_open_issues=31,
        ),
        cadence,
    )

    assert any(
        reason
        == ("37 open Issues remain unadmitted: triage_required=6, legacy_unmapped=31")
        for reason in decision.reasons
    )


def test_branch_scoped_source_residue_does_not_block_unrelated_solver_dispatch() -> (
    None
):
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        replace(
            _metrics(source_problems=1),
            source_problem_scope_counts=(("branch", 1),),
            actionable_global_source_problems=0,
        ),
        cadence,
    )

    assert ControlAction.INSPECT_SOURCES in decision.actions
    assert ControlAction.RECOVER_BLOCKERS not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions
    assert decision.desired_new_solvers == 4


def test_controller_surfaces_owner_residue_without_blocking_verified_dispatch() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            active_registry_records=8,
            raw_active_registry_records=8,
            active_registry_without_worktree=8,
        ),
        cadence,
    )

    assert ControlAction.RECOVER_OWNER_BOUND_LANE in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions
    assert ControlAction.THROTTLE_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 4


def test_controller_audits_ownerless_residue_without_recovery_wake() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            active_registry_records=3,
            raw_active_registry_records=3,
            active_registry_without_worktree=3,
            active_registry_without_worktree_owner_bound=0,
            active_registry_without_worktree_ownerless=3,
        ),
        cadence,
    )

    assert ControlAction.AUDIT_OWNERLESS_LANES in decision.actions
    assert ControlAction.RECOVER_OWNER_BOUND_LANE not in decision.actions


def test_controller_surfaces_branch_residue_as_audit_only_action() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            branch_audit_items=3,
            local_orphan_branches=2,
            remote_orphan_branches=1,
        ),
        cadence,
    )

    assert ControlAction.AUDIT_BRANCH_LIFECYCLE in decision.actions
    assert ControlAction.CLEANUP_LOCAL not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions


def test_controller_does_not_emit_branch_audit_without_branch_residue() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(_metrics(), cadence)

    assert ControlAction.AUDIT_BRANCH_LIFECYCLE not in decision.actions


def test_controller_splits_owner_bound_and_ownerless_residue_actions() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            active_registry_records=3,
            raw_active_registry_records=3,
            active_registry_without_worktree=3,
            active_registry_without_worktree_owner_bound=1,
            active_registry_without_worktree_ownerless=2,
        ),
        cadence,
    )

    assert ControlAction.RECOVER_OWNER_BOUND_LANE in decision.actions
    assert ControlAction.AUDIT_OWNERLESS_LANES in decision.actions


def test_controller_audits_unreachable_owner_residue_without_recovery_wake() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            active_registry_records=2,
            raw_active_registry_records=2,
            active_registry_without_worktree=2,
            active_registry_without_worktree_owner_bound=2,
            active_registry_without_worktree_owner_reachable=0,
            active_registry_without_worktree_owner_unreachable=2,
        ),
        cadence,
    )

    assert ControlAction.AUDIT_UNREACHABLE_OWNER_LANES in decision.actions
    assert ControlAction.RECOVER_OWNER_BOUND_LANE not in decision.actions
    assert any(
        "do not wake" in reason
        for reason in decision.reasons
        if "owner-bound active registry" in reason
    )


def test_controller_splits_reachable_and_unreachable_owner_residue() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            active_registry_records=3,
            raw_active_registry_records=3,
            active_registry_without_worktree=3,
            active_registry_without_worktree_owner_bound=2,
            active_registry_without_worktree_ownerless=1,
            active_registry_without_worktree_owner_reachable=1,
            active_registry_without_worktree_owner_unreachable=1,
        ),
        cadence,
    )

    assert ControlAction.RECOVER_OWNER_BOUND_LANE in decision.actions
    assert ControlAction.AUDIT_UNREACHABLE_OWNER_LANES in decision.actions
    assert ControlAction.AUDIT_OWNERLESS_LANES in decision.actions


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


def test_lane_scoped_hard_hold_does_not_throttle_unrelated_candidate_birth() -> None:
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))
    decision = decide_capacity(
        _metrics(
            dispatchable_candidate_issues=2,
            security_hold_lanes=1,
            security_hold_issues=1,
            security_hold_global=False,
        ),
        cadence,
    )

    assert ControlAction.RECONCILE_HOLDS in decision.actions
    assert ControlAction.THROTTLE_SOLVERS not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions
    assert decision.desired_new_solvers == 2


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


def test_dogfood_preflight_does_not_block_on_branch_scoped_source_observation() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    cadence = measure_merge_cadence((), now=now)
    metrics = replace(
        _metrics(candidate_issues=0, source_problems=1),
        source_problem_scope_counts=(("branch", 1),),
        actionable_global_source_problems=0,
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
        metrics=metrics,
        cadence=cadence,
    )

    assert readiness.ready
    assert "delivery source inventory is incomplete" not in readiness.blockers
    assert any("branch" in warning for warning in readiness.warnings)
    assert readiness.ramp_ready is False


def test_dogfood_source_warning_separates_actionable_and_raw_scope_counts() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    cadence = measure_merge_cadence((), now=now)
    metrics = replace(
        _metrics(candidate_issues=0, source_problems=35),
        source_problem_scope_counts=(("branch", 35),),
        actionable_source_problems=10,
        actionable_global_source_problems=0,
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
        metrics=metrics,
        cadence=cadence,
    )

    assert any(
        "10 actionable scoped" in warning
        and "raw source observations: branch=35" in warning
        for warning in readiness.warnings
    )


def test_dogfood_preflight_keeps_global_source_uncertainty_blocking() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    cadence = measure_merge_cadence((), now=now)
    metrics = replace(
        _metrics(candidate_issues=0, source_problems=1),
        source_problem_scope_counts=(("global", 1),),
        actionable_global_source_problems=1,
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
        metrics=metrics,
        cadence=cadence,
    )

    assert readiness.ready is False
    assert "delivery source inventory is incomplete" in readiness.blockers


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
        metrics=_metrics(
            candidate_issues=0,
            timings=PipelineTimings(merge_to_sync_samples=3),
        ),
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
        metrics=_metrics(
            candidate_issues=0,
            timings=PipelineTimings(merge_to_sync_samples=2),
        ),
        cadence=cadence,
        profile=profile,
    )

    assert readiness.canary_promotable is True
    assert readiness.warnings == ()


def test_dogfood_readiness_warns_when_recent_merges_lack_sync_telemetry() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    cadence = measure_merge_cadence(
        (now - timedelta(minutes=10), now - timedelta(minutes=5), now),
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
        metrics=_metrics(timings=PipelineTimings(merge_to_sync_samples=0)),
        cadence=cadence,
    )

    assert readiness.ready is True
    assert readiness.canary_promotable is True
    assert any("sync telemetry" in warning for warning in readiness.warnings)


def test_dogfood_readiness_clears_sync_telemetry_warning_when_sampled() -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=UTC)
    cadence = measure_merge_cadence(
        (now - timedelta(minutes=10), now - timedelta(minutes=5), now),
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
        metrics=_metrics(timings=PipelineTimings(merge_to_sync_samples=3)),
        cadence=cadence,
    )

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
            LaneInspection(
                key="PR#7-duplicate",
                registry=None,
                physical=None,
                snapshot=None,
                pull_requests=(pull_request,),
                decision=LaneDecision(
                    LaneState.UNKNOWN, NextAction.INSPECT, "duplicate observation"
                ),
            ),
        )
    )

    metrics = measure_pipeline(inventory)

    assert metrics.open_prs == 1
    assert metrics.unmapped_open_prs == 1
    assert metrics.raw_open_prs == 2
    assert asdict(metrics)["raw_open_prs"] == 2


def test_pipeline_counts_quarantined_security_pr_in_raw_open_prs() -> None:
    pull_request = PullRequestSnapshot(
        number=1376,
        url="https://example.test/pull/1376",
        branch="debug/security",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
        body="PUBLISH ONLY: security hold pending",
    )
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key="PR#1376",
                registry=None,
                physical=None,
                snapshot=None,
                pull_requests=(pull_request,),
                decision=LaneDecision(
                    LaneState.SECURITY_HOLD,
                    NextAction.INSPECT,
                    "security hold",
                ),
            ),
        ),
        isolation=IsolationSummary(quarantined_open_prs=1),
    )

    metrics = measure_pipeline(inventory)

    assert metrics.raw_open_prs == 1
    assert metrics.open_prs == 0
    assert metrics.unmapped_open_prs == 1
    assert metrics.quarantined_open_prs == 1
    assert metrics.actionable_unmapped_open_prs == 0
    assert metrics.security_hold_global is False
    assert metrics.pipeline_ready is False
    assert metrics.ramp_ready is False


def test_legacy_direct_metrics_leave_raw_open_prs_unknown() -> None:
    metrics = _metrics()

    assert metrics.raw_open_prs is None


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
            LaneInspection(
                key="#owner-bound",
                registry=replace(
                    active_record,
                    lane_id="#owner-bound",
                    branch="debug/owner-bound",
                    owner_thread_id="owner-thread",
                ),
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
    assert metrics.active_registry_records == 2
    assert metrics.raw_active_registry_records == 3
    assert metrics.active_registry_without_worktree == 2
    assert metrics.active_registry_without_worktree_owner_bound == 1
    assert metrics.active_registry_without_worktree_ownerless == 1
    assert metrics.active_registry_without_worktree_owner_reachable == 0
    assert metrics.active_registry_without_worktree_owner_unreachable == 1
    assert (
        metrics.active_registry_without_worktree_owner_bound
        + metrics.active_registry_without_worktree_ownerless
        == metrics.active_registry_records
    )
    assert metrics.malformed_active_registry_records == 1


def test_metrics_exposes_malformed_active_registry_issue_observation_without_claim() -> (
    None
):
    issue = parse_demand_issue(
        {
            "id": "I_1187",
            "number": 1187,
            "url": "https://github.com/owner/repo/issues/1187",
            "title": "Issue 1187",
            "body": "plain request",
            "updatedAt": "2026-08-22T01:00:00Z",
            "labels": [{"name": "blocked"}],
        }
    )
    problem = InventoryProblem(
        "registry",
        "feat/issue-1187-library-format-validation-20260820",
        "claim_generation must be a non-negative integer",
        identity_kind="branch",
        record_status="active",
        record_external_ids=("#1187",),
    )
    projected = project_demand_inventory(
        DemandIssueInventory((issue,), raw_count=1),
        registry_problems=(problem,),
    )
    inventory = DeliveryInventory(
        lanes=(),
        demand_issues=projected,
        source_problems=(problem,),
    )

    metrics = measure_pipeline(inventory)

    assert metrics.issues_with_malformed_active_claim == 1
    assert metrics.issues_with_active_claim == 0
    assert metrics.dispatchable_candidate_issues == 0


def test_malformed_active_registry_cardinality_deduplicates_diagnostics() -> None:
    malformed_path = Path("/tmp/malformed-active")
    inventory = DeliveryInventory(
        lanes=(),
        source_problems=(
            InventoryProblem(
                "registry",
                "debug/malformed-active",
                "claim_generation must be a non-negative integer",
                identity_kind="branch",
                record_status="active",
                record_path=malformed_path,
            ),
            InventoryProblem(
                "registry",
                "debug/malformed-active",
                "registry record is missing required field: scope",
                identity_kind="branch",
                record_status="active",
                record_path=malformed_path,
            ),
            InventoryProblem(
                "registry",
                "debug/malformed-history",
                "claim_generation must be a non-negative integer",
                identity_kind="branch",
                record_status="abandoned",
            ),
        ),
    )

    metrics = measure_pipeline(inventory)

    assert metrics.source_problems == 3
    assert metrics.malformed_active_registry_records == 1
    assert metrics.raw_active_registry_records == 1
    assert metrics.active_registry_without_worktree == 1
    assert metrics.active_registry_without_worktree_ownerless == 1
    assert metrics.active_registry_without_worktree_owner_bound == 0


def test_malformed_active_owner_bound_and_ownerless_split_is_audit_only() -> None:
    ownerless_path = Path("/tmp/malformed-ownerless")
    owner_bound_path = Path("/tmp/malformed-owner-bound")
    inventory = DeliveryInventory(
        lanes=(),
        source_problems=(
            InventoryProblem(
                "registry",
                "debug/malformed-ownerless",
                "claim_generation must be a non-negative integer",
                identity_kind="branch",
                record_status="active",
                record_path=ownerless_path,
                owner_thread_id=None,
            ),
            InventoryProblem(
                "registry",
                "debug/malformed-owner-bound",
                "claim_generation must be a non-negative integer",
                identity_kind="branch",
                record_status="active",
                record_path=owner_bound_path,
                owner_thread_id="owner-thread",
            ),
        ),
    )

    metrics = measure_pipeline(inventory)
    decision = decide_capacity(
        metrics, measure_merge_cadence((), now=datetime(2026, 8, 24, tzinfo=UTC))
    )

    assert metrics.raw_active_registry_records == 2
    assert metrics.active_registry_without_worktree == 2
    assert metrics.active_registry_without_worktree_ownerless == 1
    assert metrics.active_registry_without_worktree_owner_bound == 1
    assert ControlAction.AUDIT_OWNERLESS_LANES in decision.actions
    assert ControlAction.RECOVER_OWNER_BOUND_LANE not in decision.actions


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
    assert ControlAction.THROTTLE_SOLVERS not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions
    assert decision.desired_new_solvers == 0


def test_cleanup_pending_is_lane_local_and_does_not_throttle_unrelated_candidates() -> (
    None
):
    cadence = measure_merge_cadence((), now=datetime(2026, 8, 21, tzinfo=UTC))

    decision = decide_capacity(
        _metrics(cleanup_pending=1, open_prs=1, candidate_issues=1), cadence
    )

    assert ControlAction.CLEANUP_LOCAL in decision.actions
    assert ControlAction.THROTTLE_SOLVERS not in decision.actions
    assert ControlAction.DISPATCH_SOLVERS in decision.actions
    assert decision.desired_new_solvers == 1
