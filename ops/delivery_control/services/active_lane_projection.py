"""Project active registry records into deterministic lane decisions."""

from __future__ import annotations

from ..domain.errors import DeliverySourceError
from ..domain.inventory import LaneInspection
from ..domain.models import CheckStatus
from ..domain.observations import InventoryProblem, RegistrySnapshot
from ..domain.states import LaneFacts, derive_lane_decision
from ..ports.github import GitHubQueryPort
from ..ports.runtime import AgentRuntimePort
from .correlation import owner_reachable, scope_matches_snapshot
from .inventory_sources import InspectionSources
from .lane_projection_contract import pr_receipt_matches_registry
from .pr_contract import pull_request_holds


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
    owner_problems: list[InventoryProblem] = []
    branch_prs = sources.prs_by_branch.get(record.branch, ())
    pull_request = branch_prs[0] if len(branch_prs) == 1 else None
    is_owner_reachable = owner_reachable(runtime, record, owner_problems)
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
        and record.owner_thread_id is not None
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
    holds = pull_request_holds(pull_request)
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
    problems.extend(owner_problems)
    return LaneInspection(
        key=record.lane_id,
        registry=record,
        physical=physical_ref,
        snapshot=snapshot,
        pull_requests=branch_prs,
        decision=derive_lane_decision(facts),
        problems=tuple(problems),
        required_check=check,
        queue_entry=queue_entry,
    )
