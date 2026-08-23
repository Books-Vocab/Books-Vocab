"""Pure feedback policy; it recommends work but never dispatches an agent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .metrics import MergeCadence, PipelineMetrics


class ControlAction(StrEnum):
    INSPECT_SOURCES = "inspect_sources"
    CLEANUP_LOCAL = "cleanup_local"
    CLEANUP_TERMINAL = "cleanup_terminal"
    ENQUEUE_GREEN = "enqueue_green"
    PUBLISH_HANDBACKS = "publish_handbacks"
    AUDIT_TRANSPORT_SLO = "audit_transport_slo"
    AUDIT_QUARANTINE = "audit_quarantine"
    AUDIT_SYNC_TELEMETRY = "audit_sync_telemetry"
    AUDIT_BRANCH_LIFECYCLE = "audit_branch_lifecycle"
    AUDIT_CI_START_SLO = "audit_ci_start_slo"
    AUDIT_QUEUE_ADMISSION_SLO = "audit_queue_admission_slo"
    AUDIT_MERGE_CADENCE = "audit_merge_cadence"
    AUDIT_OWNERLESS_LANES = "audit_ownerless_lanes"
    REPAIR_PR_CONTRACT = "repair_pr_contract"
    REPAIR_REQUIRED = "repair_required"
    TRIGGER_REQUIRED = "trigger_required"
    REANCHOR_FRONT = "reanchor_front"
    REPLENISH_CANDIDATES = "replenish_candidates"
    TRIAGE_EXISTING_ISSUES = "triage_existing_issues"
    RECOVER_LEGACY_ISSUES = "recover_legacy_issues"
    RECOVER_OWNER_BOUND_LANE = "recover_owner_bound_lane"
    RECONCILE_HOLDS = "reconcile_holds"
    IMPROVE_SCOPE_PARTITION = "improve_scope_partition"
    FILL_REQUIRED_CAPACITY = "fill_required_capacity"
    RESTORE_MERGE_BUFFER = "restore_merge_buffer"
    RECOVER_MERGE_CADENCE = "recover_merge_cadence"
    RECONCILE_IDLE_WORKTREES = "reconcile_idle_worktrees"
    RECOVER_BLOCKERS = "recover_blockers"
    DISPATCH_SOLVERS = "dispatch_solvers"
    THROTTLE_SOLVERS = "throttle_solvers"
    HEALTHY = "healthy"


@dataclass(frozen=True)
class CapacityPolicy:
    min_open_prs: int = 10
    max_open_prs: int = 15
    min_candidate_issues: int = 20
    max_candidate_issues: int = 30
    target_active_solvers: int = 8
    max_active_solvers: int = 12
    min_required_running: int = 3
    max_required_running: int = 4
    min_merge_ready_or_queued: int = 3
    target_merges_per_hour: float = 12.0
    max_inter_merge_seconds: float = 300.0
    max_required_p95_seconds: float = 240.0
    max_handback_to_pr_p95_seconds: float = 60.0
    max_pr_to_required_start_p95_seconds: float = 60.0
    max_required_success_to_enqueue_p95_seconds: float = 30.0
    max_collision_pressure: float = 0.20
    max_new_solvers_per_cycle: int = 4


@dataclass(frozen=True)
class CapacityDecision:
    actions: tuple[ControlAction, ...]
    desired_new_solvers: int
    reasons: tuple[str, ...]


DEFAULT_CAPACITY_POLICY = CapacityPolicy()


def decide_capacity(
    metrics: PipelineMetrics,
    cadence: MergeCadence,
    *,
    required_p95_seconds: float | None = None,
    policy: CapacityPolicy = DEFAULT_CAPACITY_POLICY,
) -> CapacityDecision:
    actions: list[ControlAction] = []
    reasons: list[str] = []

    def add(action: ControlAction, reason: str) -> None:
        if action not in actions:
            actions.append(action)
            reasons.append(reason)

    if metrics.actionable_source_problems:
        add(ControlAction.INSPECT_SOURCES, "actionable source inventory is incomplete")
    cadence_missed = (
        cadence.merges_per_hour < policy.target_merges_per_hour
        or cadence.p95_interval_seconds is None
        or cadence.p95_interval_seconds > policy.max_inter_merge_seconds
        or cadence.seconds_since_last_merge is None
        or cadence.seconds_since_last_merge > policy.max_inter_merge_seconds
    )
    if cadence_missed:
        cadence_reason = (
            f"merge cadence is below {policy.target_merges_per_hour:g}/hour "
            "or its p95/last landing exceeds "
            f"{policy.max_inter_merge_seconds:g} seconds"
        )
        add(ControlAction.AUDIT_MERGE_CADENCE, cadence_reason)
        cadence_recovery_supply = (
            metrics.open_prs
            + metrics.handbacks_publishable
            + metrics.active_development
            + metrics.required_green
            + metrics.merge_queue_depth
        )
        if cadence_recovery_supply:
            add(
                ControlAction.RECOVER_MERGE_CADENCE,
                f"{cadence_reason}; delivery supply is available",
            )
    if metrics.reanchor_required:
        add(ControlAction.REANCHOR_FRONT, "exact stale-base PRs await reanchor")
    if not metrics.issue_inventory_complete or metrics.unadmitted_open_issues is None:
        add(
            ControlAction.TRIAGE_EXISTING_ISSUES,
            "raw open Issue inventory is incomplete; backlog cardinality is unknown",
        )
    elif metrics.unadmitted_open_issues:
        add(
            ControlAction.TRIAGE_EXISTING_ISSUES,
            (
                f"{metrics.unadmitted_open_issues} open Issues lack an explicit "
                "candidate, owner, blocked, or terminal disposition"
            ),
        )
    if metrics.legacy_open_issues:
        add(
            ControlAction.RECOVER_LEGACY_ISSUES,
            f"{metrics.legacy_open_issues} legacy Issues need migration evidence",
        )
    if metrics.actionable_blocked_lanes:
        add(
            ControlAction.RECOVER_OWNER_BOUND_LANE,
            "existing owner-bound lanes require bounded recovery",
        )
    owner_bound_registry_residue = metrics.active_registry_without_worktree_owner_bound
    if owner_bound_registry_residue is None:
        # Preserve the pre-split direct-construction contract. Measured
        # inventories always provide the explicit split, so ownerless claims
        # cannot reach the recovery action through this fallback.
        owner_bound_registry_residue = metrics.active_registry_without_worktree
    if owner_bound_registry_residue:
        add(
            ControlAction.RECOVER_OWNER_BOUND_LANE,
            (
                f"{owner_bound_registry_residue} owner-bound active registry claim(s) "
                "have no physical worktree and require original-owner recovery"
            ),
        )
    if metrics.active_registry_without_worktree_ownerless:
        add(
            ControlAction.AUDIT_OWNERLESS_LANES,
            (
                f"{metrics.active_registry_without_worktree_ownerless} ownerless active "
                "registry claim(s) have no physical worktree; audit ownership only"
            ),
        )
    if metrics.branch_audit_items:
        add(
            ControlAction.AUDIT_BRANCH_LIFECYCLE,
            (
                f"{metrics.branch_audit_items} branch asset(s) need lifecycle audit "
                f"(local orphan={metrics.local_orphan_branches}, "
                f"remote orphan={metrics.remote_orphan_branches}, "
                f"merged cleanup={metrics.merged_branch_cleanup_ready}, "
                f"remote drift={metrics.remote_drift_branches}); "
                "run branch-audit/branch-review-plan; observation only"
            ),
        )
    if metrics.security_hold_issues or metrics.security_hold_lanes:
        add(
            ControlAction.RECONCILE_HOLDS,
            "explicit P0/P1/security holds require terminal disposition",
        )
    if metrics.recoverable_quarantine:
        add(
            ControlAction.AUDIT_QUARANTINE,
            (
                f"{metrics.recoverable_quarantine} quarantined delivery observations "
                "need owner or terminal-evidence reconciliation"
            ),
        )
    if (
        cadence.merged_count
        and metrics.timings.merge_to_sync_samples < cadence.merged_count
    ):
        missing_sync_samples = (
            cadence.merged_count - metrics.timings.merge_to_sync_samples
        )
        add(
            ControlAction.AUDIT_SYNC_TELEMETRY,
            (
                f"{missing_sync_samples} recent merge landing(s) lack "
                "merge-to-main sync telemetry"
            ),
        )
    if (
        not metrics.actionable_source_problems
        and metrics.backlog_drained
        and metrics.dispatchable_candidate_issues < policy.min_candidate_issues
    ):
        add(
            ControlAction.REPLENISH_CANDIDATES,
            "unclaimed GitHub candidate Issues are below the safe reservoir",
        )
    if metrics.cleanup_pending:
        add(ControlAction.CLEANUP_LOCAL, "registry cleanup leases remain pending")
    elif metrics.published_local_cleanup:
        add(ControlAction.CLEANUP_LOCAL, "published PRs retain local assets")
    if metrics.actionable_terminal_cleanup:
        add(ControlAction.CLEANUP_TERMINAL, "merged assets remain")
    if metrics.clean_unregistered_worktrees:
        add(
            ControlAction.RECONCILE_IDLE_WORKTREES,
            "clean unregistered worktrees require owner recovery or terminal disposition",
        )
    if metrics.required_green:
        add(ControlAction.ENQUEUE_GREEN, "required-green reservoir is non-empty")
    if metrics.handbacks_publishable:
        add(ControlAction.PUBLISH_HANDBACKS, "typed handbacks await publication")
    if metrics.pr_contract_failed:
        add(ControlAction.REPAIR_PR_CONTRACT, "PR delivery contracts are invalid")
    if metrics.required_failed:
        add(ControlAction.REPAIR_REQUIRED, "required checks failed")
    if metrics.required_absent:
        add(ControlAction.TRIGGER_REQUIRED, "published PRs have no required run")
    required_candidates = max(
        0,
        metrics.open_prs
        - metrics.required_green
        - metrics.merge_queue_depth
        - metrics.required_failed
        - metrics.pr_contract_failed,
    )
    if (
        metrics.required_running < policy.min_required_running
        and required_candidates > metrics.required_running
    ):
        add(
            ControlAction.FILL_REQUIRED_CAPACITY,
            (
                "required concurrency is below the "
                f"{policy.min_required_running}-runner floor while PR work is available"
            ),
        )
    merge_buffer = metrics.required_green + metrics.merge_queue_depth
    downstream_supply = (
        metrics.open_prs + metrics.handbacks_publishable + metrics.active_development
    )
    if (
        merge_buffer < policy.min_merge_ready_or_queued
        and downstream_supply >= policy.min_merge_ready_or_queued
    ):
        add(
            ControlAction.RESTORE_MERGE_BUFFER,
            (
                "required-green plus native-queue supply is below the "
                f"{policy.min_merge_ready_or_queued}-PR floor"
            ),
        )
    if metrics.actionable_blocked_lanes:
        add(ControlAction.RECOVER_BLOCKERS, "existing lanes need bounded recovery")
    if metrics.collision_rate > policy.max_collision_pressure:
        add(
            ControlAction.IMPROVE_SCOPE_PARTITION,
            "collision-blocked live-lane pressure exceeds the safe threshold",
        )
    if (
        metrics.timings.handback_to_pr_p95_seconds is not None
        and metrics.timings.handback_to_pr_p95_seconds
        > policy.max_handback_to_pr_p95_seconds
    ):
        add(
            ControlAction.AUDIT_TRANSPORT_SLO,
            "handback-to-PR p95 exceeds the transport SLA",
        )
    if (
        metrics.timings.pr_to_required_start_p95_seconds is not None
        and metrics.timings.pr_to_required_start_p95_seconds
        > policy.max_pr_to_required_start_p95_seconds
    ):
        add(
            ControlAction.AUDIT_CI_START_SLO,
            "PR-to-required-start p95 exceeds the CI-start SLA",
        )
    if (
        metrics.timings.required_success_to_enqueue_p95_seconds is not None
        and metrics.timings.required_success_to_enqueue_p95_seconds
        > policy.max_required_success_to_enqueue_p95_seconds
    ):
        add(
            ControlAction.AUDIT_QUEUE_ADMISSION_SLO,
            "required-success-to-enqueue p95 exceeds the admission SLA",
        )

    observed_required_p95 = (
        required_p95_seconds
        if required_p95_seconds is not None
        else metrics.timings.required_duration_p95_seconds
    )
    ci_saturated = (
        observed_required_p95 is not None
        and observed_required_p95 > policy.max_required_p95_seconds
    ) or metrics.required_running > policy.max_required_running
    collision_saturated = metrics.collision_rate > policy.max_collision_pressure
    pr_saturated = metrics.open_prs >= policy.max_open_prs
    desired_new_solvers = 0
    unsafe_pr_inventory = bool(
        metrics.actionable_unmapped_open_prs or metrics.duplicate_pr_mappings
    )
    if metrics.actionable_source_problems:
        add(
            ControlAction.RECOVER_BLOCKERS,
            "solver dispatch is disabled until actionable source inventory is complete",
        )
    elif unsafe_pr_inventory:
        add(
            ControlAction.RECOVER_BLOCKERS,
            "solver dispatch is disabled until PR ownership is exact",
        )
    elif metrics.cleanup_pending:
        add(
            ControlAction.THROTTLE_SOLVERS,
            "solver dispatch is disabled while registry cleanup leases are pending",
        )
    elif metrics.security_hold_issues or metrics.security_hold_lanes:
        add(
            ControlAction.THROTTLE_SOLVERS,
            "solver dispatch is disabled while explicit hard holds remain",
        )
    elif (
        collision_saturated
        or ci_saturated
        or pr_saturated
        or metrics.active_development >= policy.max_active_solvers
    ):
        add(
            ControlAction.THROTTLE_SOLVERS,
            "collision pressure, CI, PR, or active-solver WIP reached its safe ceiling",
        )
    else:
        durable_supply = metrics.open_prs + metrics.handbacks_publishable
        durable_supply_gap = max(0, policy.min_open_prs - durable_supply)
        solver_gap = max(0, policy.target_active_solvers - metrics.active_development)
        # Active Solver capacity is a leading reservoir, not a lagging alarm.
        # Waiting until merge cadence degrades before restoring it creates a
        # predictable starvation sawtooth: the PR queue drains first, then new
        # implementation work starts too late to preserve the five-minute SLO.
        # Healthy cadence therefore does not suppress birth below the target
        # band; the independent PR/CI/collision ceilings above remain the
        # backpressure mechanisms.
        if durable_supply < policy.max_open_prs and solver_gap:
            desired_new_solvers = min(
                solver_gap,
                metrics.dispatchable_candidate_issues,
                policy.max_new_solvers_per_cycle,
                max(0, policy.max_active_solvers - metrics.active_development),
            )
            if desired_new_solvers:
                add(
                    ControlAction.DISPATCH_SOLVERS,
                    (
                        "existing unclaimed candidates can restore the active-solver "
                        f"band while durable supply is {durable_supply} "
                        f"(floor gap {durable_supply_gap})"
                    ),
                )

    if not actions:
        actions.append(ControlAction.HEALTHY)
        reasons.append("pipeline reservoirs and cadence are within policy")
    return CapacityDecision(
        actions=tuple(actions),
        desired_new_solvers=desired_new_solvers,
        reasons=tuple(reasons),
    )
