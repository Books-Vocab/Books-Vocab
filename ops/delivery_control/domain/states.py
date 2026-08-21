"""Pure lane state classification and next-action selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import CheckStatus


class LaneMode(StrEnum):
    INDEPENDENT = "independent"
    STACKED = "stacked"


class HoldKind(StrEnum):
    P0 = "p0"
    P1 = "p1"
    SECURITY = "security"


class LaneState(StrEnum):
    ACTIVE_DEVELOPMENT = "active_development"
    HANDBACK_PUBLISHABLE = "handback_publishable"
    PUBLISHED_LOCAL_CLEANUP = "published_local_cleanup"
    PR_DRAFT = "pr_draft"
    PR_WAITING_REQUIRED = "pr_waiting_required"
    REQUIRED_FAILED = "required_failed"
    READY_TO_QUEUE = "ready_to_queue"
    SECURITY_HOLD = "security_hold"
    TERMINAL_CLEANUP = "terminal_cleanup"
    DONE = "done"
    BLOCKED_DIRTY = "blocked_dirty"
    BLOCKED_OWNER = "blocked_owner"
    BLOCKED_COLLISION = "blocked_collision"
    BLOCKED_DUPLICATE = "blocked_duplicate"
    ABANDONABLE_NOOP = "abandonable_noop"
    UNKNOWN = "unknown"


class NextAction(StrEnum):
    CONTINUE_WORK = "continue_work"
    PUBLISH = "publish"
    CLEANUP_LOCAL = "cleanup_local"
    FINALIZE_PR = "finalize_pr"
    WAIT_REQUIRED = "wait_required"
    REPAIR_REQUIRED = "repair_required"
    ENQUEUE = "enqueue"
    WAIT_CLEARANCE = "wait_clearance"
    CLEANUP = "cleanup"
    RECOVER_DIRTY = "recover_dirty"
    RECOVER_OWNER = "recover_owner"
    RESOLVE_COLLISION = "resolve_collision"
    DEDUPLICATE = "deduplicate"
    ABANDON = "abandon"
    INSPECT = "inspect"
    NONE = "none"


@dataclass(frozen=True)
class LaneFacts:
    mode: LaneMode = LaneMode.INDEPENDENT
    has_worktree: bool = False
    owner_known: bool = False
    owner_reachable: bool = False
    dirty: bool = False
    has_committed_diff: bool | None = None
    handback_valid: bool = False
    published: bool = False
    local_assets_present: bool = False
    transport_policy_passed: bool = False
    merge_policy_passed: bool = False
    cleanup_policy_passed: bool = False
    abandonment_policy_passed: bool = False
    duplicate_pr: bool = False
    scope_collision: bool = False
    pr_open: bool = False
    pr_draft: bool = False
    required_status: CheckStatus = CheckStatus.ABSENT
    mergeable: bool = False
    merged: bool = False
    cleanup_complete: bool = False
    holds: frozenset[HoldKind] = frozenset()


@dataclass(frozen=True)
class LaneDecision:
    state: LaneState
    next_action: NextAction
    reason: str


def derive_lane_decision(facts: LaneFacts) -> LaneDecision:
    """Classify one lane from facts only; no I/O or mutable state is consulted."""

    if facts.duplicate_pr:
        return LaneDecision(
            LaneState.BLOCKED_DUPLICATE, NextAction.DEDUPLICATE, "duplicate PR mapping"
        )
    if facts.scope_collision:
        return LaneDecision(
            LaneState.BLOCKED_COLLISION,
            NextAction.RESOLVE_COLLISION,
            "Scope overlaps another active lane",
        )
    if facts.dirty:
        if (
            not facts.published
            and not facts.pr_open
            and facts.has_worktree
            and facts.owner_known
            and facts.owner_reachable
        ):
            return LaneDecision(
                LaneState.ACTIVE_DEVELOPMENT,
                NextAction.CONTINUE_WORK,
                "reachable owner has uncommitted work in progress",
            )
        return LaneDecision(
            LaneState.BLOCKED_DIRTY, NextAction.RECOVER_DIRTY, "worktree is dirty"
        )
    if facts.published and facts.local_assets_present:
        return LaneDecision(
            LaneState.PUBLISHED_LOCAL_CLEANUP,
            NextAction.CLEANUP_LOCAL,
            "published PR is durable; local assets remain",
        )
    if facts.has_worktree and (not facts.owner_known or not facts.owner_reachable):
        return LaneDecision(
            LaneState.BLOCKED_OWNER,
            NextAction.RECOVER_OWNER,
            "worktree owner is unavailable",
        )
    if facts.merged and facts.cleanup_complete:
        return LaneDecision(
            LaneState.DONE, NextAction.NONE, "merged assets are reconciled"
        )
    if facts.merged and facts.cleanup_policy_passed:
        return LaneDecision(
            LaneState.TERMINAL_CLEANUP, NextAction.CLEANUP, "merged assets remain"
        )
    if facts.merged:
        return LaneDecision(
            LaneState.UNKNOWN,
            NextAction.INSPECT,
            "merged lane lacks an approved cleanup policy",
        )
    if facts.holds:
        return LaneDecision(
            LaneState.SECURITY_HOLD,
            NextAction.WAIT_CLEARANCE,
            "explicit P0/P1/security hold",
        )
    if facts.pr_open and facts.pr_draft:
        return LaneDecision(LaneState.PR_DRAFT, NextAction.FINALIZE_PR, "PR is draft")
    if facts.pr_open and facts.required_status is CheckStatus.FAILURE:
        return LaneDecision(
            LaneState.REQUIRED_FAILED,
            NextAction.REPAIR_REQUIRED,
            "required check failed",
        )
    if facts.pr_open and facts.merge_policy_passed:
        return LaneDecision(
            LaneState.READY_TO_QUEUE,
            NextAction.ENQUEUE,
            "exact merge policy passed",
        )
    if facts.pr_open:
        return LaneDecision(
            LaneState.PR_WAITING_REQUIRED,
            NextAction.WAIT_REQUIRED,
            "PR awaits required checks or mergeability",
        )
    if facts.transport_policy_passed:
        return LaneDecision(
            LaneState.HANDBACK_PUBLISHABLE,
            NextAction.PUBLISH,
            "exact transport policy passed",
        )
    if facts.has_worktree and facts.abandonment_policy_passed:
        return LaneDecision(
            LaneState.ABANDONABLE_NOOP, NextAction.ABANDON, "clean worktree has no diff"
        )
    if facts.has_worktree and facts.owner_known and facts.owner_reachable:
        return LaneDecision(
            LaneState.ACTIVE_DEVELOPMENT,
            NextAction.CONTINUE_WORK,
            "owner-bound work remains active",
        )
    return LaneDecision(LaneState.UNKNOWN, NextAction.INSPECT, "insufficient facts")
