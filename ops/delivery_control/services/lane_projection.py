"""Project owner-bound registry records into deterministic lane decisions."""

from __future__ import annotations

from pathlib import Path

from ..domain.errors import DeliverySourceError
from ..domain.inventory import LaneInspection
from ..domain.models import CheckStatus
from ..domain.observations import (
    InventoryProblem,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from ..domain.states import HoldKind, LaneFacts, derive_lane_decision
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.runtime import AgentRuntimePort
from .correlation import (
    has_explicit_hold,
    owner_reachable,
    scope_matches_snapshot,
)
from .inventory_sources import InspectionSources
from .publish import parse_pull_request_body


def _pr_receipt_matches_registry(
    record: RegistrySnapshot,
    pull_request: PullRequestSnapshot,
    problems: list[InventoryProblem],
) -> bool:
    try:
        receipt = parse_pull_request_body(pull_request.body)
    except DeliverySourceError as error:
        problems.append(
            InventoryProblem("github", f"PR#{pull_request.number}", str(error))
        )
        return False
    exact = (
        receipt.lane_id == record.lane_id
        and receipt.owner_thread_id == record.owner_thread_id
        and receipt.claim_generation == record.claim_generation
        and receipt.branch == record.branch
        and Path(receipt.worktree_path).resolve() == record.path.resolve()
        and receipt.base_sha == record.base_sha
        and receipt.head_sha == record.handed_back_sha == pull_request.head_sha
        and receipt.origin_main_sha == record.handback_origin_main_sha
        and receipt.content_digest == record.handback_digest
        and receipt.scope == record.scope
        and pull_request.base_branch == "main"
    )
    if not exact:
        problems.append(
            InventoryProblem(
                "github",
                f"PR#{pull_request.number}",
                "PR receipt differs from the exact registry tuple",
            )
        )
    return exact


def project_active_lane(
    *,
    sources: InspectionSources,
    record: RegistrySnapshot,
    github: GitHubQueryPort,
    runtime: AgentRuntimePort,
) -> LaneInspection:
    path = record.path.resolve()
    physical_ref = sources.physical_by_path.get(path)
    snapshot = sources.snapshots[record.lane_id]
    problems = list(sources.lane_problems[record.lane_id])
    branch_prs = sources.prs_by_branch.get(record.branch, ())
    pull_request = branch_prs[0] if len(branch_prs) == 1 else None
    is_owner_reachable = owner_reachable(runtime, record, problems)
    check = None
    body_exact = False
    queued = False
    if pull_request is not None:
        if pull_request.state == "OPEN":
            try:
                queued = github.merge_queue_entry_id(pull_request.node_id) is not None
            except DeliverySourceError as error:
                problems.append(
                    InventoryProblem("github", f"PR#{pull_request.number}", str(error))
                )
        body_exact = _pr_receipt_matches_registry(record, pull_request, problems)
        if pull_request.state == "OPEN":
            try:
                check = github.required_check_snapshot(pull_request.number)
            except DeliverySourceError as error:
                problems.append(
                    InventoryProblem("github", f"PR#{pull_request.number}", str(error))
                )
    lane_collision = f"lane:{record.lane_id}" in sources.collisions
    scope_exact = snapshot is not None and scope_matches_snapshot(record, snapshot)
    if snapshot is not None and not scope_exact:
        problems.append(
            InventoryProblem(
                "git",
                str(path),
                "physical operations or paths differ from Scope",
            )
        )
    if pull_request is not None:
        if snapshot is None or pull_request.head_sha != snapshot.head_sha:
            problems.append(
                InventoryProblem(
                    "github",
                    f"PR#{pull_request.number}",
                    "PR HEAD differs from physical HEAD",
                )
            )
        if record.handed_back_sha != pull_request.head_sha:
            problems.append(
                InventoryProblem(
                    "github",
                    f"PR#{pull_request.number}",
                    "PR HEAD differs from registry handback",
                )
            )
    transport_exact = (
        not problems
        and not lane_collision
        and len(branch_prs) <= 1
        and is_owner_reachable
        and snapshot is not None
        and snapshot.clean
        and snapshot.path.resolve() == path
        and snapshot.branch == record.branch
        and snapshot.base_sha == record.base_sha
        and scope_exact
        and record.handback_valid
        and record.handed_back_sha == snapshot.head_sha
        and record.handback_claim_generation == record.claim_generation
    )
    holds = (
        frozenset({HoldKind.SECURITY})
        if has_explicit_hold(pull_request)
        else frozenset()
    )
    facts = LaneFacts(
        has_worktree=physical_ref is not None,
        owner_known=record.owner_thread_id is not None,
        owner_reachable=is_owner_reachable,
        dirty=snapshot is not None and not snapshot.clean,
        has_committed_diff=bool(snapshot.changes) if snapshot else None,
        handback_valid=record.handback_valid,
        published=pull_request is not None and body_exact,
        local_assets_present=pull_request is not None and body_exact,
        transport_policy_passed=transport_exact and pull_request is None,
        abandonment_policy_passed=(
            not problems
            and snapshot is not None
            and snapshot.clean
            and not snapshot.changes
            and is_owner_reachable
            and not branch_prs
        ),
        duplicate_pr=len(branch_prs) > 1,
        scope_collision=lane_collision,
        pr_open=pull_request is not None,
        pr_contract_valid=pull_request is None or body_exact,
        pr_draft=pull_request.draft if pull_request else False,
        required_status=check.status if check else CheckStatus.ABSENT,
        mergeable=pull_request.mergeable if pull_request else False,
        queued=queued,
        holds=holds,
    )
    return LaneInspection(
        key=record.lane_id,
        registry=record,
        physical=physical_ref,
        snapshot=snapshot,
        pull_requests=branch_prs,
        decision=derive_lane_decision(facts),
        problems=tuple(problems),
    )


def project_published_lane(
    *,
    sources: InspectionSources,
    record: RegistrySnapshot,
    git: GitQueryPort,
    github: GitHubQueryPort,
) -> LaneInspection:
    path = record.path.resolve()
    physical_ref = sources.physical_by_path.get(path)
    branch_prs = sources.prs_by_branch.get(record.branch, ())
    pull_request = branch_prs[0] if len(branch_prs) == 1 else None
    problems: list[InventoryProblem] = []
    snapshot = None
    if physical_ref is not None:
        try:
            snapshot = git.inspect_worktree(path, record.base_sha)
        except DeliverySourceError as error:
            problems.append(InventoryProblem("git", str(path), str(error)))
    check = None
    body_exact = False
    queued = False
    if pull_request is not None:
        if pull_request.state == "OPEN":
            try:
                queued = github.merge_queue_entry_id(pull_request.node_id) is not None
            except DeliverySourceError as error:
                problems.append(
                    InventoryProblem("github", f"PR#{pull_request.number}", str(error))
                )
        body_exact = _pr_receipt_matches_registry(record, pull_request, problems)
        if pull_request.state == "OPEN":
            try:
                check = github.required_check_snapshot(pull_request.number)
            except DeliverySourceError as error:
                problems.append(
                    InventoryProblem("github", f"PR#{pull_request.number}", str(error))
                )
        if tuple(sorted(sources.pr_paths.get(pull_request.number, ()))) != tuple(
            sorted(record.scope.paths)
        ):
            problems.append(
                InventoryProblem(
                    "github",
                    f"PR#{pull_request.number}",
                    "PR paths differ from published Scope",
                )
            )
    local_assets_present = (
        physical_ref is not None or git.local_branch_sha(record.branch) is not None
    )
    remote_assets_present = git.remote_branch_sha(record.branch) is not None
    collision_key = f"published:{record.lane_id}:{record.claim_generation}"
    lane_collision = collision_key in sources.collisions
    merge_exact = (
        not problems
        and not lane_collision
        and len(branch_prs) == 1
        and pull_request is not None
        and pull_request.state == "OPEN"
        and not queued
        and not pull_request.draft
        and pull_request.mergeable
        and pull_request.base_sha == sources.live_main_sha == record.base_sha
        and pull_request.head_sha == record.handed_back_sha
        and body_exact
        and record.handback_valid
        and record.handback_claim_generation == record.claim_generation
        and check is not None
        and check.head_sha == pull_request.head_sha
        and check.status is CheckStatus.SUCCESS
        and not has_explicit_hold(pull_request)
    )
    cleanup_exact = (
        not problems
        and not lane_collision
        and len(branch_prs) == 1
        and pull_request is not None
        and pull_request.state == "MERGED"
        and pull_request.head_sha == record.handed_back_sha
        and body_exact
        and record.handback_valid
        and record.handback_claim_generation == record.claim_generation
    )
    holds = (
        frozenset({HoldKind.SECURITY})
        if has_explicit_hold(pull_request)
        else frozenset()
    )
    return LaneInspection(
        key=f"published:{record.lane_id}:{record.claim_generation}",
        registry=record,
        physical=physical_ref,
        snapshot=snapshot,
        pull_requests=branch_prs,
        decision=derive_lane_decision(
            LaneFacts(
                has_worktree=physical_ref is not None,
                dirty=snapshot is not None and not snapshot.clean,
                handback_valid=record.handback_valid,
                published=True,
                local_assets_present=local_assets_present,
                duplicate_pr=len(branch_prs) > 1,
                scope_collision=lane_collision,
                pr_open=pull_request is not None,
                pr_contract_valid=pull_request is None or body_exact,
                pr_draft=pull_request.draft if pull_request else False,
                required_status=(check.status if check else CheckStatus.ABSENT),
                mergeable=pull_request.mergeable if pull_request else False,
                queued=queued,
                merge_policy_passed=merge_exact,
                cleanup_policy_passed=cleanup_exact,
                merged=pull_request is not None and pull_request.state == "MERGED",
                cleanup_complete=(
                    record.status == "merged"
                    and not local_assets_present
                    and not remote_assets_present
                ),
                holds=holds,
            )
        ),
        problems=tuple(problems),
    )
