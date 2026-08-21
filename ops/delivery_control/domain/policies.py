"""Pure transport and merge policies."""

from __future__ import annotations

from dataclasses import dataclass

from .models import HandbackReceipt, PullRequestSnapshot, WorktreeSnapshot
from .states import CheckStatus, HoldKind


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


def evaluate_publication(
    *,
    receipt: HandbackReceipt,
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
    if not worktree.clean:
        reasons.append("worktree is dirty")
    if worktree.branch != receipt.branch:
        reasons.append("branch differs from handback")
    if worktree.head_sha != receipt.head_sha:
        reasons.append("HEAD differs from handback")
    if worktree.parent_sha != receipt.parent_sha:
        reasons.append("parent differs from handback")
    if tuple(sorted(worktree.changed_paths)) != tuple(sorted(receipt.scope.paths)):
        reasons.append("physical paths differ from Scope")
    return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))


def evaluate_merge_gate(
    *,
    pull_request: PullRequestSnapshot,
    receipt: HandbackReceipt,
    live_main_sha: str,
    required_status: CheckStatus,
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
    if pull_request.head_sha != receipt.head_sha:
        reasons.append("PR head differs from handback")
    if pull_request.branch != receipt.branch:
        reasons.append("PR branch differs from handback")
    if required_status is not CheckStatus.SUCCESS:
        reasons.append("required checks are not successful")
    if holds:
        reasons.append("explicit hold is active")
    return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))
