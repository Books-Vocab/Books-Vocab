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
    REPAIR_REQUIRED = "repair_required"
    RECOVER_BLOCKERS = "recover_blockers"
    DISPATCH_SOLVERS = "dispatch_solvers"
    THROTTLE_SOLVERS = "throttle_solvers"
    HEALTHY = "healthy"


@dataclass(frozen=True)
class CapacityPolicy:
    min_open_prs: int = 10
    max_open_prs: int = 15
    min_required_green: int = 3
    target_merges_per_hour: float = 12.0
    max_inter_merge_seconds: float = 300.0
    max_required_p95_seconds: float = 240.0
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

    if metrics.source_problems:
        add(ControlAction.INSPECT_SOURCES, "source inventory is incomplete")
    if metrics.cleanup_pending:
        add(ControlAction.CLEANUP_LOCAL, "registry cleanup leases remain pending")
    elif metrics.published_local_cleanup:
        add(ControlAction.CLEANUP_LOCAL, "published PRs retain local assets")
    if metrics.terminal_cleanup:
        add(ControlAction.CLEANUP_TERMINAL, "merged assets remain")
    if metrics.required_green:
        add(ControlAction.ENQUEUE_GREEN, "required-green reservoir is non-empty")
    if metrics.handbacks_publishable:
        add(ControlAction.PUBLISH_HANDBACKS, "typed handbacks await publication")
    if metrics.required_failed:
        add(ControlAction.REPAIR_REQUIRED, "required checks failed")
    if metrics.blocked_lanes:
        add(ControlAction.RECOVER_BLOCKERS, "existing lanes need bounded recovery")

    ci_saturated = (
        required_p95_seconds is not None
        and required_p95_seconds > policy.max_required_p95_seconds
    )
    pr_saturated = metrics.open_prs >= policy.max_open_prs
    desired_new_solvers = 0
    unsafe_pr_inventory = bool(
        metrics.unmapped_open_prs or metrics.duplicate_pr_mappings
    )
    if metrics.source_problems:
        add(
            ControlAction.RECOVER_BLOCKERS,
            "solver dispatch is disabled until source inventory is complete",
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
    elif ci_saturated or pr_saturated:
        add(
            ControlAction.THROTTLE_SOLVERS,
            "CI latency or PR reservoir reached its safe ceiling",
        )
    else:
        durable_supply = metrics.open_prs + metrics.handbacks_publishable
        projected_supply = durable_supply + metrics.active_development
        supply_gap = max(0, policy.min_open_prs - projected_supply)
        cadence_slow = (
            cadence.merges_per_hour < policy.target_merges_per_hour
            or cadence.seconds_since_last_merge is None
            or cadence.seconds_since_last_merge > policy.max_inter_merge_seconds
        )
        if supply_gap and cadence_slow:
            desired_new_solvers = min(supply_gap, policy.max_new_solvers_per_cycle)
            add(
                ControlAction.DISPATCH_SOLVERS,
                "durable and active supply cannot sustain the merge SLO",
            )

    if not actions:
        actions.append(ControlAction.HEALTHY)
        reasons.append("pipeline reservoirs and cadence are within policy")
    return CapacityDecision(
        actions=tuple(actions),
        desired_new_solvers=desired_new_solvers,
        reasons=tuple(reasons),
    )
