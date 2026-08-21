"""Pure and source-bounded helpers for correlating delivery observations."""

from __future__ import annotations

from ..domain.errors import DeliverySourceError
from ..domain.models import ScopeOperation
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
        (
            FileOperation.ADD
            if item.operation is ScopeOperation.ADD
            else FileOperation.MODIFY,
            item.path,
        )
        for item in record.scope.files
    }
    actual = {(item.operation, item.path) for item in snapshot.changes}
    return actual == expected


def has_explicit_hold(pull_request: PullRequestSnapshot | None) -> bool:
    if pull_request is None:
        return False
    body = pull_request.body.lower()
    return "publish only" in body or "security_hold" in body or "security hold" in body


def collision_keys(path_sets: dict[str, set[str]]) -> set[str]:
    keys = sorted(path_sets)
    collisions: set[str] = set()
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            if path_sets[left].intersection(path_sets[right]):
                collisions.update((left, right))
    return collisions
