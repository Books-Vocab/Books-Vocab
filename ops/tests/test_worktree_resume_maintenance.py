from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.models import CheckStatus
from delivery_control.domain.observations import (
    CheckSnapshot,
    MergeQueueEntrySnapshot,
    PullRequestInventory,
    PullRequestSnapshot,
)
from worktree_reanchor_core.errors import ReanchorRefused
from worktree_reanchor_core.lifecycle_proof import (
    verify_resume_lifecycle,
)
from worktree_reanchor_core.resume_domain import build_request

BASE = "1" * 40
HEAD = "3" * 40


def _pr() -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=1468,
        url="https://example.test/pull/1468",
        branch="debug/delivery-observation-batch-20260823",
        base_sha=BASE,
        head_sha=HEAD,
        state="OPEN",
        draft=False,
        mergeable=True,
        node_id="PR_1468",
        body="typed handback",
    )


def _check(status: CheckStatus) -> CheckSnapshot:
    return CheckSnapshot(
        status=status,
        head_sha=HEAD,
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
        names=("required",),
    )


class FakeGitHub:
    def __init__(self, check: CheckSnapshot) -> None:
        self.pr = _pr()
        self.check = check

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory((self.pr,))

    def merge_queue_entry_snapshot(
        self, pull_request_id: str
    ) -> MergeQueueEntrySnapshot | None:
        return None

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        return self.check


def test_maintenance_resume_accepts_exact_required_success() -> None:
    proof = verify_resume_lifecycle(
        FakeGitHub(_check(CheckStatus.SUCCESS)),
        branch="debug/delivery-observation-batch-20260823",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
        require_failed=False,
    )

    assert proof.required_status is CheckStatus.SUCCESS


def test_maintenance_resume_accepts_exact_required_pending() -> None:
    proof = verify_resume_lifecycle(
        FakeGitHub(_check(CheckStatus.PENDING)),
        branch="debug/delivery-observation-batch-20260823",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
        require_failed=False,
    )

    assert proof.required_status is CheckStatus.PENDING


def test_maintenance_resume_rejects_missing_required_observation() -> None:
    with pytest.raises(ReanchorRefused, match="required check"):
        verify_resume_lifecycle(
            FakeGitHub(_check(CheckStatus.ABSENT)),
            branch="debug/delivery-observation-batch-20260823",
            expected_base_sha=BASE,
            expected_remote_head=HEAD,
            require_failed=False,
        )


def test_resume_request_requires_explicit_known_mode(tmp_path: Path) -> None:
    with pytest.raises(ReanchorRefused, match="resume mode"):
        build_request(
            repo=tmp_path,
            state_path=tmp_path / "registry.json",
            lane_id="DIRECT-TEST",
            branch="feat/test",
            owner_thread_id="owner",
            claim_generation=0,
            expected_remote_head=HEAD,
            target=tmp_path / "worktree",
            mode="unknown",
        )
