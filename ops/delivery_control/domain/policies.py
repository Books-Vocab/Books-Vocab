"""Pure transport and merge policies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import CheckStatus, HandbackReceipt
from .observations import (
    CheckSnapshot,
    FileOperation,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from .states import HoldKind


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


def evaluate_publication(
    *,
    receipt: HandbackReceipt,
    registry: RegistrySnapshot,
    worktree: WorktreeSnapshot,
    duplicate_pr: bool,
    scope_collision: bool,
) -> PolicyDecision:
    """Validate transport invariants without treating current base or quality as gates."""

    reasons: list[str] = []
    if duplicate_pr:
        reasons.append("duplicate PR exists")
    if scope_collision:
        reasons.append("Scope collision exists")
    if registry.status != "active":
        reasons.append("registry claim is not active")
    if registry.lane_id != receipt.lane_id:
        reasons.append("registry lane differs from handback")
    if registry.owner_thread_id != receipt.owner_thread_id:
        reasons.append("registry owner differs from handback")
    if registry.claim_generation != receipt.claim_generation:
        reasons.append("registry generation differs from handback")
    if registry.branch != receipt.branch:
        reasons.append("registry branch differs from handback")
    if (
        registry.path.resolve() != worktree.path.resolve()
        or registry.path.resolve() != Path(receipt.worktree_path).resolve()
    ):
        reasons.append("worktree path differs from owner claim")
    if registry.base_sha != receipt.base_sha:
        reasons.append("registry base differs from handback")
    if registry.scope != receipt.scope:
        reasons.append("registry Scope differs from handback")
    if not worktree.clean:
        reasons.append("worktree is dirty")
    if worktree.branch != receipt.branch:
        reasons.append("branch differs from handback")
    if worktree.base_sha != receipt.base_sha:
        reasons.append("base differs from handback")
    if worktree.head_sha != receipt.head_sha:
        reasons.append("HEAD differs from handback")
    if worktree.parent_sha != receipt.parent_sha:
        reasons.append("parent differs from handback")
    expected_changes = frozenset(
        (FileOperation(item.operation.value), item.path) for item in receipt.scope.files
    )
    actual_changes = frozenset((item.operation, item.path) for item in worktree.changes)
    if not actual_changes or not actual_changes.issubset(expected_changes):
        reasons.append("physical operations or paths differ from Scope")
    return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))


def evaluate_merge_gate(
    *,
    pull_request: PullRequestSnapshot,
    receipt: HandbackReceipt,
    live_main_sha: str,
    registry: RegistrySnapshot,
    required: CheckSnapshot,
    holds: frozenset[HoldKind] = frozenset(),
) -> PolicyDecision:
    reasons: list[str] = []
    if pull_request.state != "OPEN":
        reasons.append("PR is not open")
    if pull_request.draft:
        reasons.append("PR is draft")
    if not pull_request.mergeable:
        reasons.append("PR is not mergeable")
    if pull_request.base_sha != live_main_sha or receipt.base_sha != live_main_sha:
        reasons.append("PR or handback base is stale")
    if registry.base_sha != live_main_sha:
        reasons.append("registry base is stale")
    if pull_request.head_sha != receipt.head_sha:
        reasons.append("PR head differs from handback")
    if pull_request.branch != receipt.branch:
        reasons.append("PR branch differs from handback")
    if registry.lane_id != receipt.lane_id:
        reasons.append("registry lane differs from handback")
    if registry.owner_thread_id != receipt.owner_thread_id:
        reasons.append("registry owner differs from handback")
    if registry.claim_generation != receipt.claim_generation:
        reasons.append("registry generation differs from handback")
    if registry.scope != receipt.scope:
        reasons.append("registry Scope differs from handback")
    if registry.handed_back_sha != receipt.head_sha or not registry.handback_valid:
        reasons.append("registry handback is not exact")
    if required.head_sha != pull_request.head_sha:
        reasons.append("required checks belong to another HEAD")
    if required.status is not CheckStatus.SUCCESS:
        reasons.append("required checks are not successful")
    if holds:
        reasons.append("explicit hold is active")
    return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))
