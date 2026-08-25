"""Read-only branch lifecycle report over the complete delivery inventory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from ..domain.branch_lifecycle import (
    BranchAsset,
    BranchCleanupAction,
    BranchDisposition,
    BranchRegistryEvidence,
    BranchSide,
)
from ..domain.inventory import DeliveryInventory
from ..domain.observations import InventoryProblem, RegistrySnapshot
from ..domain.unreachable_commits import (
    EMPTY_UNREACHABLE_COMMIT_INVENTORY,
    UnreachableCommitEvidence,
    UnreachableCommitInventory,
)
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
    review_command: str | None = None
    owner_thread_ids: tuple[str, ...] = ()
    paired_ref_side: BranchSide | None = None
    paired_ref_sha: str | None = None


@dataclass(frozen=True)
class BranchAuditRegistryAction:
    """One active registry claim with no corresponding observed Git asset.

    Branch lifecycle projection is intentionally ref-oriented.  A registry
    claim can nevertheless survive after its local/remote refs and physical
    worktree have disappeared.  Keep that claim visible as its own action
    rather than fabricating a branch SHA or silently dropping it from the
    audit.
    """

    lane_id: str
    branch: str
    path: str
    status: str
    claim_generation: int
    base_sha: str
    handed_back_sha: str | None
    owner_thread_id: str | None
    registry_evidence: BranchRegistryEvidence
    category: str
    safe_terminal: bool
    next_step: str
    suggested_command: str | None = None


class SourceProblemActionability(StrEnum):
    """Whether a source problem blocks a currently observed delivery asset."""

    BLOCKING = "blocking"
    QUARANTINED_HISTORY = "quarantined_history"


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
    record_status: str | None = None
    actionability: SourceProblemActionability = SourceProblemActionability.BLOCKING
    record_external_ids: tuple[str, ...] = ()


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
    raw_active_registry_records: int
    malformed_registry_records: int
    published_registry_records: int
    open_pull_requests: int
    unreachable_commit_count: int
    unreachable_commit_sample: tuple[str, ...]
    unreachable_commit_evidence: tuple[UnreachableCommitEvidence, ...]
    unreachable_commit_next_step: str
    disposition_counts: dict[str, int]
    action_counts: dict[str, int]
    assets: tuple[BranchAsset, ...]
    actions: tuple[BranchAuditAction, ...]
    safe_terminal_actions: tuple[BranchAuditAction, ...]
    registry_only_actions: tuple[BranchAuditRegistryAction, ...]
    registry_only_status_counts: dict[str, int]
    source_problems: tuple[InventoryProblem, ...]
    source_problem_actions: tuple[BranchAuditSourceProblem, ...]
    registry_record_problem_actions: tuple[BranchAuditSourceProblem, ...]
    actionable_source_problems: int
    quarantined_source_problems: int
    registry_record_problem_status_counts: dict[str, int]
    source_problem_counts: dict[str, int]
    source_problem_scope_counts: dict[str, int]


def _source_problem_action(
    problem: InventoryProblem,
    *,
    actionability: SourceProblemActionability = SourceProblemActionability.BLOCKING,
) -> BranchAuditSourceProblem:
    """Project one incomplete source into an observable, non-mutating action."""

    source = problem.source
    affected_branch = (
        problem.identity
        if problem.source == "registry" and problem.identity_kind == "branch"
        else None
    )
    if source == "git" and problem.identity_kind == "git_objects":
        category = "git_source_problem"
        scope = "git_objects"
        next_step = (
            "preserve unreachable Git object diagnostics; correlate them with an "
            "owner, Issue, or PR independently and do not treat them as proof to "
            "delete or recover branch assets"
        )
    elif source == "registry":
        scope = "branch" if affected_branch is not None else "global"
        category = "registry_source_problem"
        if actionability is SourceProblemActionability.QUARANTINED_HISTORY:
            next_step = (
                "preserve this quarantined registry history; no matching "
                "local/remote branch, physical worktree, or PR is observed; "
                "do not treat it as active WIP"
            )
        elif affected_branch is None:
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
        scope = "global"
        category = "github_source_problem"
        next_step = (
            "refresh the exact GitHub inventory; do not publish, discard, or delete "
            "branch assets while PR evidence is incomplete"
        )
    elif source == "git":
        scope = "global"
        category = "git_source_problem"
        next_step = (
            "refresh the canonical Git observation; do not classify branch reachability "
            "as cleanup proof"
        )
    else:
        scope = "global"
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
        record_status=problem.record_status,
        actionability=actionability,
        record_external_ids=problem.record_external_ids,
    )


def _observed_branch_names(inventory: DeliveryInventory) -> frozenset[str]:
    names = {asset.branch for asset in inventory.branch_lifecycle.assets}
    names.update(
        worktree.branch
        for worktree in inventory.physical_worktrees
        if worktree.branch is not None
    )
    names.update(
        pull_request.branch
        for lane in inventory.lanes
        for pull_request in lane.pull_requests
    )
    return frozenset(names)


def _source_problem_actionability(
    problem: InventoryProblem,
    *,
    observed_branches: frozenset[str],
) -> SourceProblemActionability:
    if (
        problem.source == "registry"
        and problem.identity_kind == "branch"
        and problem.identity not in observed_branches
    ):
        return SourceProblemActionability.QUARANTINED_HISTORY
    return SourceProblemActionability.BLOCKING


def _withheld_by_source_problem(
    action: BranchAuditAction,
    *,
    source_problem_actions: tuple[BranchAuditSourceProblem, ...],
) -> BranchAuditAction:
    """Remove mutation affordances only for affected or globally unknown sources."""

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


def _registry_only_action(
    record: RegistrySnapshot,
) -> BranchAuditRegistryAction:
    """Expose a non-terminal registry claim absent from all observed refs."""

    if record.status == "active":
        next_step = (
            f"recover the original owner for {record.branch} through the supported "
            "lifecycle; no local/remote ref, physical worktree, or PR is observed, "
            "so do not resolve or delete this claim from the audit"
        )
    else:
        next_step = (
            f"reconcile the {record.status} claim for {record.branch} through its "
            "published/terminal receipt; no local/remote ref, physical worktree, "
            "or PR is observed, so do not mutate it from the audit"
        )
    return BranchAuditRegistryAction(
        lane_id=record.lane_id,
        branch=record.branch,
        path=str(record.path.resolve()),
        status=record.status,
        claim_generation=record.claim_generation,
        base_sha=record.base_sha,
        handed_back_sha=record.handed_back_sha,
        owner_thread_id=record.owner_thread_id,
        category="registry_only_residue",
        safe_terminal=False,
        next_step=next_step,
        registry_evidence=BranchRegistryEvidence.from_snapshot(record),
    )


def _registry_only_actions(
    inventory: DeliveryInventory,
    *,
    assets: tuple[BranchAsset, ...],
) -> tuple[BranchAuditRegistryAction, ...]:
    """Return one action for every non-terminal claim absent from Git facts."""

    observed_branches = {asset.branch for asset in assets}
    actions = tuple(
        _registry_only_action(record)
        for lane in inventory.lanes
        if (record := lane.registry) is not None
        and record.status in {"active", "published", "cleanup_pending"}
        and record.branch not in observed_branches
    )
    return tuple(sorted(actions, key=lambda item: (item.branch, item.lane_id)))


def _action_for_asset(
    asset: BranchAsset,
    *,
    orphan_preflight: OrphanBranchPreflight | None = None,
    remote_orphan_preflight: OrphanBranchPreflight | None = None,
) -> BranchAuditAction:
    if asset.disposition is BranchDisposition.PROTECTED:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            owner_thread_ids=asset.owner_thread_ids,
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
            owner_thread_ids=asset.owner_thread_ids,
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
            owner_thread_ids=asset.owner_thread_ids,
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
            owner_thread_ids=asset.owner_thread_ids,
            category="safe_terminal_candidate" if safe_terminal else "inspect",
            safe_terminal=safe_terminal,
            next_step=(
                "run the exact merged cleanup CAS command"
                if safe_terminal
                else "reconcile merged proof before cleanup"
            ),
            suggested_command=command,
        )
    if asset.disposition is BranchDisposition.SUPERSEDED_BY_MERGED_PR:
        evidence = next(
            (
                item
                for item in asset.registry_evidence
                if item.superseded_pr_number is not None
                and item.handed_back_sha is not None
            ),
            None,
        )
        safe_terminal = evidence is not None
        command = (
            "./ops/delivery.py supersede-abandoned-handback "
            f"--branch {asset.branch} --expected-head-sha "
            f"{evidence.handed_back_sha}"
            if evidence is not None
            else None
        )
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            owner_thread_ids=asset.owner_thread_ids,
            category=("safe_terminal_candidate" if safe_terminal else "inspect"),
            safe_terminal=safe_terminal,
            next_step=(
                "run the exact superseded-handback CAS command"
                if safe_terminal
                else "reconcile superseded proof before cleanup"
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
            owner_thread_ids=asset.owner_thread_ids,
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
            review_command=(
                "./ops/delivery.py branch-inspect "
                f"--branch {asset.branch} --expected-head-sha {asset.sha}"
                if not eligible
                else None
            ),
        )
    if asset.disposition is BranchDisposition.ORPHAN_REMOTE_RECONCILE:
        preflight = remote_orphan_preflight
        eligible = preflight is not None and preflight.eligible
        blockers = (
            "; ".join(preflight.blockers)
            if preflight is not None
            else "exact remote orphan preflight has not run"
        )
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            owner_thread_ids=asset.owner_thread_ids,
            category=(
                "safe_terminal_candidate" if eligible else "remote_orphan_reconcile"
            ),
            safe_terminal=eligible,
            next_step=(
                "run the exact discard-orphan-remote-branch CAS command"
                if eligible
                else f"resolve exact preflight blockers: {blockers}"
            ),
            suggested_command=(
                "./ops/delivery.py discard-orphan-remote-branch "
                f"--branch {asset.branch} --expected-head-sha {asset.sha}"
                if eligible
                else None
            ),
            orphan_preflight=preflight,
        )
    if asset.disposition is BranchDisposition.ABANDONED_WITH_HANDBACK:
        return BranchAuditAction(
            branch=asset.branch,
            side=asset.side,
            sha=asset.sha,
            disposition=asset.disposition,
            cleanup_action=asset.cleanup_action,
            owner_thread_ids=asset.owner_thread_ids,
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
            owner_thread_ids=asset.owner_thread_ids,
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
        owner_thread_ids=asset.owner_thread_ids,
        category="inspect",
        safe_terminal=False,
        next_step="inspect exact registry, PR, worktree, and remote-drift evidence",
    )


def _with_paired_ref(
    action: BranchAuditAction,
    asset: BranchAsset,
) -> BranchAuditAction:
    """Add exact sibling-ref evidence without changing the action semantics."""

    return replace(
        action,
        paired_ref_side=asset.paired_ref_side,
        paired_ref_sha=asset.paired_ref_sha,
    )


def build_branch_audit(
    inventory: DeliveryInventory,
    *,
    orphan_preflights: Mapping[str, OrphanBranchPreflight] | None = None,
    remote_orphan_preflights: Mapping[str, OrphanBranchPreflight] | None = None,
    unreachable_commits: UnreachableCommitInventory = EMPTY_UNREACHABLE_COMMIT_INVENTORY,
) -> BranchAuditReport:
    """Build a one-to-one action list without performing any mutation."""

    assets = inventory.branch_lifecycle.assets
    source_problems = inventory.source_problems + tuple(
        InventoryProblem(
            "git",
            "unreachable-commits",
            problem,
            identity_kind="git_objects",
        )
        for problem in unreachable_commits.problems
    )
    preflights = orphan_preflights or {}
    remote_preflights = remote_orphan_preflights or {}
    registry_only_actions = _registry_only_actions(inventory, assets=assets)
    observed_branches = _observed_branch_names(inventory)
    source_problem_actions = tuple(
        _source_problem_action(
            problem,
            actionability=_source_problem_actionability(
                problem,
                observed_branches=observed_branches,
            ),
        )
        for problem in source_problems
    )
    registry_record_problem_actions = tuple(
        problem
        for problem in source_problem_actions
        if problem.source == "registry" and problem.record_status is not None
    )
    actions = tuple(
        _with_paired_ref(
            _action_for_asset(
                asset,
                orphan_preflight=preflights.get(asset.branch),
                remote_orphan_preflight=remote_preflights.get(asset.branch),
            ),
            asset,
        )
        for asset in assets
    )
    complete = (
        not source_problems
        and not registry_only_actions
        and not any(asset.disposition is BranchDisposition.UNKNOWN for asset in assets)
    )
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
    malformed_registry_records = len(registry_record_problem_actions)
    malformed_active_record_identities = {
        (problem.identity_kind, problem.identity, problem.record_status)
        for problem in registry_record_problem_actions
        if problem.record_status == "active"
    }
    raw_active_registry_records = active_records + len(
        malformed_active_record_identities
    )
    published_records = sum(
        lane.registry is not None
        and lane.registry.status in {"published", "cleanup_pending"}
        for lane in inventory.lanes
    )
    unreachable_commit_next_step = (
        "correlate unreachable commit objects with an owner, Issue, or PR; "
        "preserve them and never create a branch or delete them automatically"
        if unreachable_commits.count
        else "no unreachable commit objects observed"
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
        raw_active_registry_records=raw_active_registry_records,
        malformed_registry_records=malformed_registry_records,
        published_registry_records=published_records,
        open_pull_requests=len(open_prs),
        unreachable_commit_count=unreachable_commits.count,
        unreachable_commit_sample=unreachable_commits.sample,
        unreachable_commit_evidence=unreachable_commits.evidence,
        unreachable_commit_next_step=unreachable_commit_next_step,
        disposition_counts=inventory.branch_lifecycle.counts,
        action_counts={
            action: sum(item.cleanup_action.value == action for item in actions)
            for action in BranchCleanupAction
        },
        assets=assets,
        actions=actions,
        safe_terminal_actions=tuple(item for item in actions if item.safe_terminal),
        registry_only_actions=registry_only_actions,
        registry_only_status_counts={
            status: sum(item.status == status for item in registry_only_actions)
            for status in sorted({item.status for item in registry_only_actions})
        },
        source_problems=source_problems,
        source_problem_actions=source_problem_actions,
        registry_record_problem_actions=registry_record_problem_actions,
        actionable_source_problems=sum(
            item.actionability is SourceProblemActionability.BLOCKING
            for item in source_problem_actions
        ),
        quarantined_source_problems=sum(
            item.actionability is SourceProblemActionability.QUARANTINED_HISTORY
            for item in source_problem_actions
        ),
        registry_record_problem_status_counts={
            status: sum(
                item.record_status == status for item in registry_record_problem_actions
            )
            for status in sorted(
                {
                    item.record_status
                    for item in registry_record_problem_actions
                    if item.record_status is not None
                }
            )
        },
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
    "BranchAuditRegistryAction",
    "BranchAuditReport",
    "BranchAuditSourceProblem",
    "build_branch_audit",
]
