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
    verify_reanchor_lifecycle,
    verify_resume_lifecycle,
)

BASE = "1" * 40
LIVE = "2" * 40
HEAD = "3" * 40
OTHER_HEAD = "4" * 40


def _pr(
    number: int,
    *,
    branch: str | None = None,
    base: str = BASE,
    head: str = HEAD,
    state: str = "OPEN",
    draft: bool = False,
    mergeable: bool = True,
    body: str = "",
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://example.test/pull/{number}",
        branch=branch or f"feat/pr-{number}",
        base_sha=base,
        head_sha=head,
        state=state,
        draft=draft,
        mergeable=mergeable,
        node_id=f"PR_{number}",
        body=body,
    )


def _check(
    status: CheckStatus,
    *,
    head: str = HEAD,
    names: tuple[str, ...] = ("required",),
) -> CheckSnapshot:
    return CheckSnapshot(
        status=status,
        head_sha=head,
        observed_at=datetime(2026, 8, 22, tzinfo=UTC),
        names=names,
    )


class FakeGitHub:
    def __init__(
        self,
        *,
        all_for_branch: tuple[PullRequestSnapshot, ...],
        open_prs: tuple[PullRequestSnapshot, ...] | None = None,
        checks: dict[int, CheckSnapshot] | None = None,
        queued: frozenset[int] = frozenset(),
    ) -> None:
        self.all_for_branch = all_for_branch
        self.open_prs = open_prs if open_prs is not None else all_for_branch
        self.checks = checks or {}
        self.queued = queued

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory(
            tuple(item for item in self.all_for_branch if item.branch == branch)
        )

    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory(self.open_prs)

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        return self.checks[number]

    def merge_queue_entry_snapshot(
        self, pull_request_id: str
    ) -> MergeQueueEntrySnapshot | None:
        number = int(pull_request_id.removeprefix("PR_"))
        if number not in self.queued:
            return None
        return MergeQueueEntrySnapshot(
            entry_id=f"MQ_{number}",
            enqueued_at=datetime(2026, 8, 22, tzinfo=UTC),
        )


def test_resume_lifecycle_accepts_only_exact_open_required_code_failure() -> None:
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        checks={42: _check(CheckStatus.FAILURE)},
    )

    proof = verify_resume_lifecycle(
        github,
        branch="feat/exact-pr",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
    )

    assert proof.pull_request_number == 42
    assert proof.base_sha == BASE
    assert proof.head_sha == HEAD
    assert proof.required_status is CheckStatus.FAILURE


@pytest.mark.parametrize(
    ("github", "reason"),
    [
        (
            FakeGitHub(
                all_for_branch=(
                    _pr(42, branch="feat/exact-pr"),
                    _pr(43, branch="feat/exact-pr"),
                )
            ),
            "exactly one PR",
        ),
        (
            FakeGitHub(
                all_for_branch=(
                    _pr(42, branch="feat/exact-pr", state="MERGED"),
                )
            ),
            "OPEN",
        ),
        (
            FakeGitHub(
                all_for_branch=(_pr(42, branch="feat/exact-pr"),),
                queued=frozenset({42}),
            ),
            "queue",
        ),
        (
            FakeGitHub(
                all_for_branch=(
                    _pr(42, branch="feat/exact-pr", head=OTHER_HEAD),
                )
            ),
            "HEAD",
        ),
        (
            FakeGitHub(
                all_for_branch=(_pr(42, branch="feat/exact-pr"),),
                checks={42: _check(CheckStatus.SUCCESS)},
            ),
            "required code failure",
        ),
        (
            FakeGitHub(
                all_for_branch=(_pr(42, branch="feat/exact-pr"),),
                checks={
                    42: _check(
                        CheckStatus.FAILURE,
                        names=("validate PR readiness contract",),
                    )
                },
            ),
            "required code failure",
        ),
    ],
)
def test_resume_lifecycle_rejects_non_code_failure_or_ambiguous_pr(
    github: FakeGitHub,
    reason: str,
) -> None:
    with pytest.raises(ReanchorRefused, match=reason):
        verify_resume_lifecycle(
            github,
            branch="feat/exact-pr",
            expected_base_sha=BASE,
            expected_remote_head=HEAD,
        )


def test_reanchor_lifecycle_accepts_oldest_required_green_unheld_pr() -> None:
    candidate = _pr(42, branch="feat/exact-pr")
    later = _pr(43, head=OTHER_HEAD)
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(later, candidate),
        checks={
            42: _check(CheckStatus.SUCCESS),
            43: _check(CheckStatus.SUCCESS, head=OTHER_HEAD),
        },
    )

    proof = verify_reanchor_lifecycle(
        github,
        pull_request_number=42,
        branch="feat/exact-pr",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
        live_main_sha=LIVE,
    )

    assert proof.pull_request_number == 42
    assert proof.merge_front_policy == "lowest-required-green-unheld-pr-number"


def test_reanchor_lifecycle_rejects_caller_selected_non_front_pr() -> None:
    earlier = _pr(41, head=OTHER_HEAD)
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate, earlier),
        checks={
            41: _check(CheckStatus.SUCCESS, head=OTHER_HEAD),
            42: _check(CheckStatus.SUCCESS),
        },
    )

    with pytest.raises(ReanchorRefused, match="deterministic merge-front"):
        verify_reanchor_lifecycle(
            github,
            pull_request_number=42,
            branch="feat/exact-pr",
            expected_base_sha=candidate.base_sha,
            expected_remote_head=HEAD,
            live_main_sha=LIVE,
        )


def test_reanchor_lifecycle_defers_to_existing_native_queue_entry() -> None:
    candidate = _pr(42, branch="feat/exact-pr")
    queued = _pr(43, head=OTHER_HEAD)
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate, queued),
        checks={42: _check(CheckStatus.SUCCESS)},
        queued=frozenset({43}),
    )

    with pytest.raises(ReanchorRefused, match="native merge queue"):
        verify_reanchor_lifecycle(
            github,
            pull_request_number=42,
            branch="feat/exact-pr",
            expected_base_sha=BASE,
            expected_remote_head=HEAD,
            live_main_sha=LIVE,
        )


@pytest.mark.parametrize(
    ("candidate", "check", "reason"),
    [
        (_pr(42, branch="feat/exact-pr", base=LIVE), _check(CheckStatus.SUCCESS), "stale"),
        (_pr(42, branch="feat/exact-pr", draft=True), _check(CheckStatus.SUCCESS), "draft"),
        (_pr(42, branch="feat/exact-pr", mergeable=False), _check(CheckStatus.SUCCESS), "mergeable"),
        (_pr(42, branch="feat/exact-pr"), _check(CheckStatus.FAILURE), "required-green"),
        (
            _pr(42, branch="feat/exact-pr", body="P0 hold"),
            _check(CheckStatus.SUCCESS),
            "hold",
        ),
    ],
)
def test_reanchor_lifecycle_rejects_ineligible_candidate(
    candidate: PullRequestSnapshot,
    check: CheckSnapshot,
    reason: str,
) -> None:
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate,),
        checks={42: check},
    )

    with pytest.raises(ReanchorRefused, match=reason):
        verify_reanchor_lifecycle(
            github,
            pull_request_number=42,
            branch="feat/exact-pr",
            expected_base_sha=candidate.base_sha,
            expected_remote_head=HEAD,
            live_main_sha=LIVE,
        )
