"""Read-only branch lifecycle report over the complete delivery inventory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from ..domain.branch_lifecycle import (
    BranchAsset,
    BranchCleanupAction,
    BranchDisposition,
    BranchSide,
)
from ..domain.inventory import DeliveryInventory
from ..domain.observations import InventoryProblem
from .orphan_branch import OrphanBranchPreflight


@dataclass(frozen=True)
class BranchAuditAction:
    """One deterministic next action for one observed branch ref."""

    branch: str
    side: BranchSide
    sha: str
    disposition: BranchDisposition
    cleanup_action: BranchCleanupAction
    category: str
    safe_terminal: bool
    next_step: str
    suggested_command: str | None = None
    orphan_preflight: OrphanBranchPreflight | None = None


@dataclass(frozen=True)
class BranchAuditSourceProblem:
    """One source failure with a deterministic recovery instruction."""

    source: str
    identity: str
    reason: str
    category: str
    next_step: str
    identity_kind: str | None = None
    scope: str = "global"
    affected_branch: str | None = None


@dataclass(frozen=True)
class BranchAuditReport:
    """Machine-readable branch inventory; it never authorizes mutation."""

    schema: str
    complete: bool
    verdict: str
    live_main_sha: str | None
    local_main_sha: str | None
    raw_local_branches: int
    raw_remote_branches: int
    physical_worktrees: int
    active_registry_records: int
    published_registry_records: int
    open_pull_requests: int
    disposition_counts: dict[str, int]
    action_counts: dict[str, int]
    assets: tuple[BranchAsset, ...]
    actions: tuple[BranchAuditAction, ...]
    safe_terminal_actions: tuple[BranchAuditAction, ...]
    source_problems: tuple[InventoryProblem, ...]
    source_problem_actions: tuple[BranchAuditSourceProblem, ...]
    source_problem_counts: dict[str, int]
    source_problem_scope_counts: dict[str, int]


def _source_problem_action(problem: InventoryProblem) -> BranchAuditSourceProblem:
    """Project one incomplete source into an observable, non-mutating action."""

    source = problem.source
    affected_branch = (
        problem.identity
        if problem.source == "registry" and problem.identity_kind == "branch"
        else None
    )
    scope = "branch" if affected_branch is not None else "global"
    if source == "registry":
        category = "registry_source_problem"
        if affected_branch is None:
            next_step = (
                "preserve all branch/worktree assets; the malformed registry identity "
                "cannot be scoped safely, so reconcile it through its supported "
                "owner lifecycle before cleanup"
            )
        else:
            next_step = (
                f"preserve {affected_branch} assets; reconcile its malformed registry "
                "record through the supported owner lifecycle before cleanup"
            )
    elif source == "github":
        category = "github_source_problem"
        next_step = (
            "refresh the exact GitHub inventory; do not publish, discard, or delete "
            "branch assets while PR evidence is incomplete"
        )
    elif source == "git":
        category = "git_source_problem"
        next_step = (
            "refresh the canonical Git observation; do not classify branch reachability "
            "as cleanup proof"
        )
    else:
        category = "delivery_source_problem"
        next_step = (
            "resolve the source inventory problem through the owning adapter before "
            "any lifecycle mutation"
        )
    return BranchAuditSourceProblem(
        source=source,
        identity=problem.identity,
        reason=problem.reason,
        category=category,
        next_step=next_step,
        identity_kind=problem.identity_kind,
        scope=scope,
        affected_branch=affected_branch,
    )


def _withheld_by_source_problem(
    action: BranchAuditAction,
    *,
    source_problem_actions: tuple[BranchAuditSourceProblem, ...],
) -> BranchAuditAction:
    """Remove mutation affordances only for affected or globally unknown sources."""

    if not action.safe_terminal:
        return action
    relevant = tuple(
        problem
        for problem in source_problem_actions
        if problem.scope == "global" or problem.affected_branch == action.branch
    )
    if not relevant:
        return action
    details = "; ".join(f"{problem.source}:{problem.identity}" for problem in relevant)
    return replace(
        action,
        category="source_incomplete",
        safe_terminal=False,
        next_step=(
            "resolve source inventory problems affecting this branch before using "
            f"the otherwise eligible cleanup action ({details})"
        ),
        suggested_command=None,
    )


def _action_for_asset(
    asset: BranchAsset,
    *,
    orphan_preflight: OrphanBranchPreflight | None = None,
) -> BranchAuditAction:
    if asset.disposition is BranchDisposition.PROTECTED:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category="preserve",
            safe_terminal=False,
            next_step="preserve protected branch; no cleanup",
        )
    if asset.disposition is BranchDisposition.OPEN_PR_DURABLE:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category="durable_pr",
            safe_terminal=False,
            next_step="preserve durable PR; PI/CM owns the next lifecycle step",
        )
    if asset.disposition is BranchDisposition.ACTIVE_OR_PUBLISHED_LANE:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category="owner_lane",
            safe_terminal=False,
            next_step="follow the original owner lane; do not delete or take over",
        )
    if asset.disposition is BranchDisposition.MERGED_CLEANUP_READY:
        command = None
        safe_terminal = len(asset.pull_request_numbers) == 1
        if safe_terminal:
            command = (
                f"./ops/delivery.py cleanup-merged --pr {asset.pull_request_numbers[0]}"
            )
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category="safe_terminal_candidate" if safe_terminal else "inspect",
            safe_terminal=safe_terminal,
            next_step=(
                "run the exact merged cleanup CAS command"
                if safe_terminal
                else "reconcile merged proof before cleanup"
            ),
            suggested_command=command,
        )
    if asset.disposition is BranchDisposition.ORPHAN_LOCAL_RECONCILE:
        eligible = orphan_preflight is not None and orphan_preflight.eligible
        blockers = (
            "; ".join(orphan_preflight.blockers)
            if orphan_preflight is not None
            else "exact orphan preflight has not run"
        )
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category=(
                "safe_terminal_candidate" if eligible else "local_orphan_blocked"
            ),
            safe_terminal=eligible,
            next_step=(
                "run the exact discard-orphan CAS command"
                if eligible
                else f"resolve exact preflight blockers: {blockers}"
            ),
            suggested_command=(
                "./ops/delivery.py discard-orphan-branch "
                f"--branch {asset.branch} --expected-head-sha {asset.sha}"
                if eligible
                else None
            ),
            orphan_preflight=orphan_preflight,
        )
    if asset.disposition is BranchDisposition.ORPHAN_REMOTE_RECONCILE:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category="remote_orphan_reconcile",
            safe_terminal=False,
            next_step="reconcile the original owner/lifecycle; never delete from audit",
        )
    if asset.disposition is BranchDisposition.ABANDONED_WITH_HANDBACK:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category="abandoned_handback",
            safe_terminal=False,
            next_step="recover the owner or obtain explicit discard proof",
        )
    if asset.disposition is BranchDisposition.CLOSED_DISPOSITION_REQUIRED:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            category="closed_pr_reconcile",
            safe_terminal=False,
            next_step="reconcile the closed PR through its supported lifecycle",
        )
    return BranchAuditAction(
        branch=asset.branch,
        side=asset.side,
        sha=asset.sha,
        disposition=asset.disposition,
        cleanup_action=asset.cleanup_action,
        category="inspect",
        safe_terminal=False,
        next_step="inspect exact registry, PR, worktree, and remote-drift evidence",
    )


def build_branch_audit(
    inventory: DeliveryInventory,
    *,
    orphan_preflights: Mapping[str, OrphanBranchPreflight] | None = None,
) -> BranchAuditReport:
    """Build a one-to-one action list without performing any mutation."""

    assets = inventory.branch_lifecycle.assets
    preflights = orphan_preflights or {}
    source_problem_actions = tuple(
        _source_problem_action(problem) for problem in inventory.source_problems
    )
    actions = tuple(
        _action_for_asset(asset, orphan_preflight=preflights.get(asset.branch))
        for asset in assets
    )
    complete = not inventory.source_problems
    if not complete:
        actions = tuple(
            _withheld_by_source_problem(
                action, source_problem_actions=source_problem_actions
            )
            for action in actions
        )
    open_prs = {
        pull_request.number
        for lane in inventory.lanes
        for pull_request in lane.pull_requests
        if pull_request.state == "OPEN"
    }
    active_records = sum(
        lane.registry is not None and lane.registry.status == "active"
        for lane in inventory.lanes
    )
    published_records = sum(
        lane.registry is not None
        and lane.registry.status in {"published", "cleanup_pending"}
        for lane in inventory.lanes
    )
    return BranchAuditReport(
        schema="kg.delivery.branch-audit.v1",
        complete=complete,
        verdict="complete" if complete else "incomplete",
        live_main_sha=inventory.live_main_sha,
        local_main_sha=inventory.local_main_sha,
        raw_local_branches=len(inventory.branch_lifecycle.local),
        raw_remote_branches=len(inventory.branch_lifecycle.remote),
        physical_worktrees=len(inventory.physical_worktrees),
        active_registry_records=active_records,
        published_registry_records=published_records,
        open_pull_requests=len(open_prs),
        disposition_counts=inventory.branch_lifecycle.counts,
        action_counts={
            action: sum(item.cleanup_action.value == action for item in actions)
            for action in BranchCleanupAction
        },
        assets=assets,
        actions=actions,
        safe_terminal_actions=tuple(item for item in actions if item.safe_terminal),
        source_problems=inventory.source_problems,
        source_problem_actions=source_problem_actions,
        source_problem_counts={
            source: sum(item.source == source for item in source_problem_actions)
            for source in sorted({item.source for item in source_problem_actions})
        },
        source_problem_scope_counts={
            scope: sum(item.scope == scope for item in source_problem_actions)
            for scope in sorted({item.scope for item in source_problem_actions})
        },
    )


__all__ = [
    "BranchAuditAction",
    "BranchAuditReport",
    "BranchAuditSourceProblem",
    "build_branch_audit",
]
