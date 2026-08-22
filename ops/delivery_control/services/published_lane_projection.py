"""Project published registry records into deterministic lane decisions."""

from __future__ import annotations

from ..domain.errors import DeliverySourceError
from ..domain.inventory import LaneInspection
from ..domain.models import CheckStatus
from ..domain.observations import InventoryProblem, RegistrySnapshot
from ..domain.states import LaneFacts, derive_lane_decision
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from .inventory_sources import InspectionSources
from .lane_projection_contract import pr_receipt_matches_registry
from .pr_contract import pull_request_holds


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
    queue_entry = None
    if pull_request is not None:
        if pull_request.state == "OPEN":
            try:
                queue_entry = github.merge_queue_entry_snapshot(pull_request.node_id)
                queued = queue_entry is not None
            except DeliverySourceError as error:
                problems.append(
                    InventoryProblem("github", f"PR#{pull_request.number}", str(error))
                )
        body_exact = pr_receipt_matches_registry(record, pull_request, problems)
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
        physical_ref is not None
        or record.branch in sources.branch_inventory.local_by_name
    )
    remote_assets_present = record.branch in sources.branch_inventory.remote_by_name
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
        and not pull_request_holds(pull_request)
    )
    reanchor_exact = (
        not problems
        and not lane_collision
        and len(branch_prs) == 1
        and pull_request is not None
        and pull_request.state == "OPEN"
        and not queued
        and not pull_request.draft
        and pull_request.mergeable
        and pull_request.base_sha == record.base_sha
        and pull_request.base_sha != sources.live_main_sha
        and pull_request.head_sha == record.handed_back_sha
        and body_exact
        and record.handback_valid
        and record.handback_claim_generation == record.claim_generation
        and check is not None
        and check.head_sha == pull_request.head_sha
        and check.status is CheckStatus.SUCCESS
        and not pull_request_holds(pull_request)
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
    holds = pull_request_holds(pull_request)
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
                source_problem=bool(problems),
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
                reanchor_policy_passed=reanchor_exact,
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
        required_check=check,
        queue_entry=queue_entry,
    )
