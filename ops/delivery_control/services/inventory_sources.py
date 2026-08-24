"""Acquire and correlate read-only source facts before lane projection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ..domain.branch_refs import BranchInventory
from ..domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateIssue,
    unclaimed_candidate_issues,
)
from ..domain.demand_issues import (
    EMPTY_DEMAND_INVENTORY,
    DemandIssueInventory,
)
from ..domain.errors import DeliverySourceError
from ..domain.observations import (
    InventoryProblem,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from .correlation import collision_keys, inspect_registered
from .demand_projection import project_demand_inventory

ACTIVE = "active"
PUBLISHED = "published"
CLEANUP_PENDING = "cleanup_pending"
MERGED = "merged"
ABANDONED = "abandoned"
_REGISTRY_STATUSES = {
    ACTIVE,
    PUBLISHED,
    CLEANUP_PENDING,
    MERGED,
    ABANDONED,
}


@dataclass(frozen=True)
class InspectionSources:
    records: tuple[RegistrySnapshot, ...]
    active_records: tuple[RegistrySnapshot, ...]
    published_records: tuple[RegistrySnapshot, ...]
    physical: tuple[PhysicalWorktree, ...]
    pull_requests: tuple[PullRequestSnapshot, ...]
    demand_issues: DemandIssueInventory
    candidate_issues: tuple[CandidateIssue, ...]
    dispatchable_candidate_issues: tuple[CandidateIssue, ...]
    issue_source_problems: tuple[InventoryProblem, ...]
    live_main_sha: str
    local_main_sha: str
    branch_inventory: BranchInventory
    physical_by_path: dict[Path, PhysicalWorktree]
    prs_by_branch: dict[str, tuple[PullRequestSnapshot, ...]]
    snapshots: dict[str, WorktreeSnapshot | None]
    lane_problems: dict[str, tuple[InventoryProblem, ...]]
    pr_paths: dict[int, tuple[str, ...]]
    collisions: frozenset[str]
    source_problems: tuple[InventoryProblem, ...]


def collect_inventory_sources(
    *,
    registry: RegistryQueryPort,
    git: GitQueryPort,
    github: GitHubQueryPort,
) -> InspectionSources:
    registry_inventory = registry.list_records()
    physical = git.list_worktrees()
    pr_mapping_problems: list[InventoryProblem] = []
    try:
        github_inventory = github.list_open_pull_requests()
    except DeliverySourceError as error:
        problem = InventoryProblem("github", "open-prs", str(error))
        github_inventory = PullRequestInventory(records=(), problems=(problem,))
    github_problems = list(github_inventory.problems)
    pr_mapping_problems.extend(github_inventory.problems)
    raw_issue_inventory = EMPTY_DEMAND_INVENTORY
    list_open_issues = getattr(github, "list_open_issues", None)
    raw_issue_inventory_available = callable(list_open_issues)
    if raw_issue_inventory_available:
        try:
            raw_issue_inventory = list_open_issues()
        except DeliverySourceError as error:
            raw_issue_inventory = DemandIssueInventory(
                records=(),
                raw_count=None,
                complete=False,
                problems=(InventoryProblem("github", "open-issues", str(error)),),
            )
        github_problems.extend(raw_issue_inventory.problems)
    else:
        # Compatibility for narrow test doubles and legacy service callers.
        # The production GitHubCliAdapter implements this port; a missing
        # method here must not make unrelated PR/worktree unit tests fail.
        raw_issue_inventory = EMPTY_DEMAND_INVENTORY
    candidate_records: tuple[CandidateIssue, ...] = ()
    if not raw_issue_inventory_available or not raw_issue_inventory.complete:
        try:
            candidate_inventory = github.list_open_candidate_issues()
        except DeliverySourceError as error:
            github_problems.append(
                InventoryProblem("github", CANDIDATE_ISSUE_LABEL, str(error))
            )
        else:
            candidate_records = candidate_inventory.records
            github_problems.extend(candidate_inventory.problems)
    branch_inventory = git.branch_inventory()
    live_main_sha = git.origin_main_sha()
    local_main_sha = git.local_main_sha()
    invalid_registry_statuses = tuple(
        InventoryProblem(
            "registry",
            item.lane_id,
            f"unsupported registry status: {item.status!r}",
        )
        for item in registry_inventory.records
        if item.status not in _REGISTRY_STATUSES
    )
    records = tuple(
        item for item in registry_inventory.records if item.status in _REGISTRY_STATUSES
    )
    active_records = tuple(item for item in records if item.status == ACTIVE)
    published_records = tuple(
        item for item in records if item.status in {PUBLISHED, CLEANUP_PENDING}
    )
    physical_by_path = {item.path.resolve(): item for item in physical}
    pull_requests = list(github_inventory.records)
    known_pr_numbers = {item.number for item in pull_requests}
    open_branches = {item.branch for item in pull_requests}
    for record in published_records:
        if record.branch in open_branches:
            continue
        try:
            github_branch_inventory = github.list_pull_requests_for_branch(
                record.branch
            )
        except DeliverySourceError as error:
            github_problems.append(
                InventoryProblem("github", record.branch, str(error))
            )
            continue
        github_problems.extend(github_branch_inventory.problems)
        for pull_request in github_branch_inventory.records:
            if pull_request.number not in known_pr_numbers:
                pull_requests.append(pull_request)
                known_pr_numbers.add(pull_request.number)

    mutable_prs_by_branch: dict[str, list[PullRequestSnapshot]] = {}
    for pull_request in pull_requests:
        mutable_prs_by_branch.setdefault(pull_request.branch, []).append(pull_request)
    prs_by_branch = {
        branch: tuple(pull_requests)
        for branch, pull_requests in mutable_prs_by_branch.items()
    }

    snapshots: dict[str, WorktreeSnapshot | None] = {}
    lane_problems: dict[str, tuple[InventoryProblem, ...]] = {}
    for record in active_records:
        problems: list[InventoryProblem] = []
        snapshots[record.lane_id] = inspect_registered(
            git,
            record,
            physical_by_path.get(record.path.resolve()),
            problems,
        )
        lane_problems[record.lane_id] = tuple(problems)

    pr_paths: dict[int, tuple[str, ...]] = {}
    for pull_request in pull_requests:
        try:
            pr_paths[pull_request.number] = github.changed_paths(pull_request.number)
        except DeliverySourceError as error:
            pr_paths[pull_request.number] = ()
            github_problems.append(
                InventoryProblem("github", f"PR#{pull_request.number}", str(error))
            )

    projected_demand = project_demand_inventory(
        raw_issue_inventory,
        registry_records=records,
        pull_requests=tuple(pull_requests),
        registry_problems=registry_inventory.problems,
    )
    if pr_mapping_problems:
        projected_demand = replace(
            projected_demand,
            problems=tuple(
                dict.fromkeys(
                    (*projected_demand.problems, *pr_mapping_problems),
                )
            ),
            complete=False,
        )
    if raw_issue_inventory_available and raw_issue_inventory.complete:
        candidate_records = projected_demand.candidate_issues
    candidate_issues = unclaimed_candidate_issues(
        candidate_records,
        external_ids=tuple(
            external_id
            for item in records
            if item.status in {ACTIVE, PUBLISHED, CLEANUP_PENDING}
            for external_id in (item.external_ids or (item.lane_id,))
        ),
    )
    dispatchable_candidate_issues = unclaimed_candidate_issues(
        projected_demand.dispatchable_candidate_issues,
        external_ids=tuple(
            external_id
            for item in records
            if item.status in {ACTIVE, PUBLISHED, CLEANUP_PENDING}
            for external_id in (item.external_ids or (item.lane_id,))
        ),
    )
    if pr_mapping_problems:
        dispatchable_candidate_issues = ()

    path_sets: dict[str, set[str]] = {}
    for record in active_records:
        observed = set(record.scope.paths)
        snapshot = snapshots[record.lane_id]
        if snapshot is not None:
            observed.update(snapshot.changed_paths)
        for pull_request in prs_by_branch.get(record.branch, ()):
            observed.update(pr_paths.get(pull_request.number, ()))
        path_sets[f"lane:{record.lane_id}"] = observed

    working_branches = {item.branch for item in (*active_records, *published_records)}
    working_paths = {
        item.path.resolve() for item in (*active_records, *published_records)
    }
    for pull_request in pull_requests:
        if pull_request.branch not in working_branches:
            path_sets[f"pr:{pull_request.number}"] = set(
                pr_paths.get(pull_request.number, ())
            )
    active_branch_names = {item.branch for item in active_records}
    for record in published_records:
        if record.branch in active_branch_names:
            continue
        key = f"published:{record.lane_id}:{record.claim_generation}"
        observed = set(record.scope.paths)
        for pull_request in prs_by_branch.get(record.branch, ()):
            observed.update(pr_paths.get(pull_request.number, ()))
        path_sets[key] = observed
    for physical_ref in physical:
        if physical_ref.branch == "main" and physical_ref.head_sha == local_main_sha:
            continue
        path = physical_ref.path.resolve()
        if path in working_paths:
            continue
        try:
            snapshot = git.inspect_worktree(path, live_main_sha)
        except DeliverySourceError:
            continue
        path_sets[f"worktree:{path}"] = set(snapshot.changed_paths)

    return InspectionSources(
        records=records,
        active_records=active_records,
        published_records=published_records,
        physical=physical,
        pull_requests=tuple(pull_requests),
        demand_issues=projected_demand,
        candidate_issues=candidate_issues,
        dispatchable_candidate_issues=dispatchable_candidate_issues,
        issue_source_problems=projected_demand.problems,
        live_main_sha=live_main_sha,
        local_main_sha=local_main_sha,
        branch_inventory=branch_inventory,
        physical_by_path=physical_by_path,
        prs_by_branch=prs_by_branch,
        snapshots=snapshots,
        lane_problems=lane_problems,
        pr_paths=pr_paths,
        collisions=frozenset(collision_keys(path_sets)),
        source_problems=(
            registry_inventory.problems
            + invalid_registry_statuses
            + tuple(
                problem
                for problem in github_problems
                if (
                    problem not in projected_demand.problems
                    or problem in pr_mapping_problems
                )
            )
        ),
    )
