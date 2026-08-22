"""Pure and source-bounded helpers for correlating delivery observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..domain.errors import DeliverySourceError
from ..domain.observations import (
    FileOperation,
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from ..ports.git import GitQueryPort
from ..ports.runtime import AgentRuntimePort

UNREACHABLE_OWNER_STATES = {
    "",
    "archived",
    "not_found",
    "notloaded",
    "shutdown",
    "unknown",
    "usage-limited",
}


def owner_reachable(
    runtime: AgentRuntimePort,
    record: RegistrySnapshot,
    problems: list[InventoryProblem],
) -> bool:
    if record.owner_thread_id is None:
        return False
    try:
        status = runtime.owner_status(record.owner_thread_id).strip().lower()
    except DeliverySourceError as error:
        problems.append(InventoryProblem("runtime", record.owner_thread_id, str(error)))
        return False
    return status not in UNREACHABLE_OWNER_STATES


def inspect_registered(
    git: GitQueryPort,
    record: RegistrySnapshot,
    physical_ref: PhysicalWorktree | None,
    problems: list[InventoryProblem],
) -> WorktreeSnapshot | None:
    if physical_ref is None:
        if record.status == "active":
            problems.append(
                InventoryProblem(
                    "git", str(record.path), "registered worktree is missing"
                )
            )
        return None
    try:
        return git.inspect_worktree(record.path, record.base_sha)
    except DeliverySourceError as error:
        problems.append(InventoryProblem("git", str(record.path), str(error)))
        return None


def scope_matches_snapshot(
    record: RegistrySnapshot, snapshot: WorktreeSnapshot
) -> bool:
    expected = {
        (FileOperation(item.operation.value), item.path) for item in record.scope.files
    }
    actual = {(item.operation, item.path) for item in snapshot.changes}
    return actual == expected


def collision_keys(path_sets: dict[str, set[str]]) -> set[str]:
    keys = sorted(path_sets)
    collisions: set[str] = set()
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            if path_sets[left].intersection(path_sets[right]):
                collisions.update((left, right))
    return collisions


def delivery_collision_path_sets(
    *,
    active_records: Sequence[RegistrySnapshot],
    published_records: Sequence[RegistrySnapshot],
    physical: Sequence[PhysicalWorktree],
    snapshots: Mapping[str, WorktreeSnapshot | None],
    prs_by_branch: Mapping[str, Sequence[PullRequestSnapshot]],
    pr_paths: Mapping[int, Sequence[str]],
    local_main_sha: str,
    excluded_physical_paths: frozenset[Path] = frozenset(),
    unregistered_snapshots: Mapping[Path, WorktreeSnapshot | None] | None = None,
) -> dict[str, set[str]]:
    """Build collision inputs for the delivery inventory boundary.

    The caller supplies snapshots for unregistered physical worktrees because
    reading Git belongs to the adapter/service boundary.  Explicitly excluded
    supervision checkouts never enter this projection; an unlisted checkout
    remains a delivery source and is therefore still eligible to collide.
    """

    path_sets: dict[str, set[str]] = {}
    physical_snapshots = unregistered_snapshots or {}
    for record in active_records:
        observed = set(record.scope.paths)
        snapshot = snapshots.get(record.lane_id)
        if snapshot is not None:
            observed.update(snapshot.changed_paths)
        for pull_request in prs_by_branch.get(record.branch, ()):
            observed.update(pr_paths.get(pull_request.number, ()))
        path_sets[f"lane:{record.lane_id}"] = observed

    working_branches = {item.branch for item in (*active_records, *published_records)}
    working_paths = {
        item.path.resolve() for item in (*active_records, *published_records)
    }
    for pull_request_branch, pull_requests in prs_by_branch.items():
        if pull_request_branch not in working_branches:
            for pull_request in pull_requests:
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
        path = physical_ref.path.resolve()
        if path in excluded_physical_paths:
            continue
        if physical_ref.branch == "main" and physical_ref.head_sha == local_main_sha:
            continue
        if path in working_paths:
            continue
        snapshot = physical_snapshots.get(path)
        if snapshot is not None:
            path_sets[f"worktree:{path}"] = set(snapshot.changed_paths)
    return path_sets
