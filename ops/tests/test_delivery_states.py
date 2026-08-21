from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.models import (
    HandbackReceipt,
    PullRequestSnapshot,
    Scope,
    WorktreeSnapshot,
)
from delivery_control.domain.policies import evaluate_merge_gate, evaluate_publication
from delivery_control.domain.states import (
    CheckStatus,
    HoldKind,
    LaneFacts,
    LaneState,
    NextAction,
    derive_lane_decision,
)


@pytest.mark.parametrize(
    ("facts", "state", "action"),
    [
        (
            LaneFacts(duplicate_pr=True),
            LaneState.BLOCKED_DUPLICATE,
            NextAction.DEDUPLICATE,
        ),
        (
            LaneFacts(scope_collision=True),
            LaneState.BLOCKED_COLLISION,
            NextAction.RESOLVE_COLLISION,
        ),
        (
            LaneFacts(merged=True, cleanup_complete=True),
            LaneState.DONE,
            NextAction.NONE,
        ),
        (LaneFacts(merged=True), LaneState.TERMINAL_CLEANUP, NextAction.CLEANUP),
        (
            LaneFacts(pr_open=True, holds=frozenset({HoldKind.SECURITY})),
            LaneState.SECURITY_HOLD,
            NextAction.WAIT_CLEARANCE,
        ),
        (
            LaneFacts(pr_open=True, pr_draft=True),
            LaneState.PR_DRAFT,
            NextAction.FINALIZE_PR,
        ),
        (
            LaneFacts(pr_open=True, required_status=CheckStatus.FAILURE),
            LaneState.REQUIRED_FAILED,
            NextAction.REPAIR_REQUIRED,
        ),
        (
            LaneFacts(
                pr_open=True, required_status=CheckStatus.SUCCESS, mergeable=True
            ),
            LaneState.READY_TO_QUEUE,
            NextAction.ENQUEUE,
        ),
        (
            LaneFacts(pr_open=True, required_status=CheckStatus.PENDING),
            LaneState.PR_WAITING_REQUIRED,
            NextAction.WAIT_REQUIRED,
        ),
        (
            LaneFacts(handback_valid=True),
            LaneState.HANDBACK_PUBLISHABLE,
            NextAction.PUBLISH,
        ),
        (LaneFacts(dirty=True), LaneState.BLOCKED_DIRTY, NextAction.RECOVER_DIRTY),
        (
            LaneFacts(has_worktree=True, owner_known=True, owner_reachable=True),
            LaneState.ACTIVE_DEVELOPMENT,
            NextAction.CONTINUE_WORK,
        ),
        (
            LaneFacts(has_worktree=True, owner_known=False),
            LaneState.BLOCKED_OWNER,
            NextAction.RECOVER_OWNER,
        ),
        (
            LaneFacts(has_worktree=True, owner_known=True, has_committed_diff=False),
            LaneState.ABANDONABLE_NOOP,
            NextAction.ABANDON,
        ),
        (LaneFacts(), LaneState.UNKNOWN, NextAction.INSPECT),
    ],
)
def test_lane_state_is_derived_deterministically(
    facts: LaneFacts,
    state: LaneState,
    action: NextAction,
) -> None:
    decision = derive_lane_decision(facts)
    assert decision.state is state
    assert decision.next_action is action


def test_duplicate_beats_a_superficially_ready_pr() -> None:
    decision = derive_lane_decision(
        LaneFacts(
            duplicate_pr=True,
            pr_open=True,
            required_status=CheckStatus.SUCCESS,
            mergeable=True,
        )
    )
    assert decision.state is LaneState.BLOCKED_DUPLICATE


def _receipt(*, base_sha: str = "a" * 40) -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="DIRECT-1",
        owner_thread_id="thread-1",
        branch="feat/example",
        worktree_path="/tmp/example",
        base_sha=base_sha,
        parent_sha=base_sha,
        head_sha="b" * 40,
        origin_main_sha="c" * 40,
        content_digest="d" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


def test_publication_policy_does_not_require_current_base_or_local_quality() -> None:
    receipt = _receipt(base_sha="a" * 40)
    worktree = WorktreeSnapshot(
        path=Path("/tmp/example"),
        branch=receipt.branch,
        head_sha=receipt.head_sha,
        parent_sha=receipt.parent_sha,
        clean=True,
        changed_paths=receipt.scope.paths,
    )
    assert evaluate_publication(
        receipt=receipt,
        worktree=worktree,
        duplicate_pr=False,
        scope_collision=False,
    ).allowed


def test_merge_policy_requires_exact_live_base_required_success_and_no_hold() -> None:
    receipt = _receipt(base_sha="a" * 40)
    pull_request = PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        state="OPEN",
        draft=False,
        mergeable=True,
    )
    allowed = evaluate_merge_gate(
        pull_request=pull_request,
        receipt=receipt,
        live_main_sha="a" * 40,
        required_status=CheckStatus.SUCCESS,
    )
    stale = evaluate_merge_gate(
        pull_request=pull_request,
        receipt=receipt,
        live_main_sha="c" * 40,
        required_status=CheckStatus.SUCCESS,
    )
    held = evaluate_merge_gate(
        pull_request=pull_request,
        receipt=receipt,
        live_main_sha="a" * 40,
        required_status=CheckStatus.SUCCESS,
        holds=frozenset({HoldKind.SECURITY}),
    )
    assert allowed.allowed
    assert not stale.allowed
    assert "stale" in " ".join(stale.reasons)
    assert not held.allowed
