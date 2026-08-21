"""Acquire and correlate read-only source facts before lane projection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import DeliverySourceError
from ..domain.observations import (
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from .correlation import collision_keys, inspect_registered

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
    live_main_sha: str
    local_main_sha: str
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
    github_inventory = github.list_open_pull_requests()
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
    github_problems = list(github_inventory.problems)
    known_pr_numbers = {item.number for item in pull_requests}
    open_branches = {item.branch for item in pull_requests}
    for record in published_records:
        if record.branch in open_branches:
            continue
        try:
            branch_inventory = github.list_pull_requests_for_branch(record.branch)
        except DeliverySourceError as error:
            github_problems.append(
                InventoryProblem("github", record.branch, str(error))
            )
            continue
        github_problems.extend(branch_inventory.problems)
        for pull_request in branch_inventory.records:
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
        live_main_sha=live_main_sha,
        local_main_sha=local_main_sha,
        physical_by_path=physical_by_path,
        prs_by_branch=prs_by_branch,
        snapshots=snapshots,
        lane_problems=lane_problems,
        pr_paths=pr_paths,
        collisions=frozenset(collision_keys(path_sets)),
        source_problems=(
            registry_inventory.problems
            + invalid_registry_statuses
            + tuple(github_problems)
        ),
    )
