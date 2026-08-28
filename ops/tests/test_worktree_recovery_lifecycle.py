from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.models import (
    CheckStatus,
    HandbackReceipt,
    Scope,
)
from delivery_control.domain.observations import (
    CheckSnapshot,
    MergeQueueEntrySnapshot,
    PullRequestInventory,
    PullRequestSnapshot,
)
from delivery_control.services.pr_contract import render_pull_request_body
from worktree_reanchor_core import git_ops
from worktree_reanchor_core.errors import ReanchorRefused
from worktree_reanchor_core.lifecycle_proof import (
    verify_reanchor_lifecycle,
    verify_resume_lifecycle,
)

BASE = "1" * 40
LIVE = "2" * 40
HEAD = "3" * 40
OTHER_HEAD = "4" * 40


def test_reanchor_git_timeout_is_structured_and_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[0] == ["git", "status"]
        assert kwargs["timeout"] == git_ops.REANCHOR_GIT_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"partial")

    monkeypatch.setattr(git_ops.subprocess, "run", timeout)

    return_code, output = git_ops._git(["status"], tmp_path)

    assert return_code == 124
    assert output == "partial\ngit command timed out after 120s"


def _receipt_body(
    *,
    number: int,
    branch: str,
    base: str,
    head: str,
) -> str:
    receipt = HandbackReceipt(
        lane_id=f"DIRECT-PR-{number}",
        owner_thread_id="owner-thread-1",
        claim_generation=0,
        branch=branch,
        worktree_path=f"/tmp/pr-{number}",
        base_sha=base,
        parent_sha=base,
        head_sha=head,
        origin_main_sha=base,
        content_digest="e" * 64,
        scope=Scope.from_paths(modify=(f"ops/pr_{number}.py",)),
    )
    return render_pull_request_body(receipt)


def _pr(
    number: int,
    *,
    branch: str | None = None,
    base: str = BASE,
    head: str = HEAD,
    state: str = "OPEN",
    draft: bool = False,
    mergeable: bool = True,
    body: str | None = None,
) -> PullRequestSnapshot:
    actual_branch = branch or f"feat/pr-{number}"
    actual_head = head
    actual_base = base
    return PullRequestSnapshot(
        number=number,
        url=f"https://example.test/pull/{number}",
        branch=actual_branch,
        base_sha=actual_base,
        head_sha=actual_head,
        state=state,
        draft=draft,
        mergeable=mergeable,
        node_id=f"PR_{number}",
        body=(
            _receipt_body(
                number=number,
                branch=actual_branch,
                base=actual_base,
                head=actual_head,
            )
            if body is None
            else body
        ),
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


def test_resume_lifecycle_ignores_advisory_agent_review_for_required_code_failure() -> (
    None
):
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        checks={
            42: _check(
                CheckStatus.FAILURE,
                names=("agent-review", "required"),
            )
        },
    )

    proof = verify_resume_lifecycle(
        github,
        branch="feat/exact-pr",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
    )

    assert proof.required_status is CheckStatus.FAILURE


def test_resume_lifecycle_rejects_agent_review_without_required_context() -> None:
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        checks={42: _check(CheckStatus.SUCCESS, names=("agent-review",))},
    )

    with pytest.raises(ReanchorRefused, match="exact required code context"):
        verify_resume_lifecycle(
            github,
            branch="feat/exact-pr",
            expected_base_sha=BASE,
            expected_remote_head=HEAD,
        )


def test_maintenance_resume_accepts_combined_required_context() -> None:
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        checks={
            42: _check(
                CheckStatus.SUCCESS,
                names=("agent-review", "required"),
            )
        },
    )

    proof = verify_resume_lifecycle(
        github,
        branch="feat/exact-pr",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
        require_failed=False,
    )

    assert proof.required_status is CheckStatus.SUCCESS


def test_maintenance_resume_deduplicates_repeated_agent_review_context() -> None:
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        checks={
            42: _check(
                CheckStatus.SUCCESS,
                names=("agent-review", "agent-review", "required"),
            )
        },
    )

    proof = verify_resume_lifecycle(
        github,
        branch="feat/exact-pr",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
        require_failed=False,
    )

    assert proof.required_status is CheckStatus.SUCCESS


def test_reanchor_lifecycle_accepts_required_green_with_optional_agent_review_context() -> (
    None
):
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        checks={
            42: _check(
                CheckStatus.SUCCESS,
                names=("agent-review", "required"),
            )
        },
        open_prs=(candidate,),
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
    assert proof.required_status is CheckStatus.SUCCESS


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
                all_for_branch=(_pr(42, branch="feat/exact-pr", state="MERGED"),)
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
                all_for_branch=(_pr(42, branch="feat/exact-pr", head=OTHER_HEAD),)
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
            "required code context",
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


def test_reanchor_lifecycle_ignores_unrelated_pr_without_required_checks() -> None:
    candidate = _pr(42, branch="feat/exact-pr")
    unrelated = _pr(43, branch="feat/unrelated")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate, unrelated),
        checks={
            42: _check(CheckStatus.SUCCESS),
            43: _check(CheckStatus.ABSENT, head=HEAD, names=()),
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


def test_reanchor_lifecycle_skips_earlier_pr_with_mismatched_typed_receipt() -> None:
    malformed = _pr(
        41,
        branch="feat/earlier",
        head=OTHER_HEAD,
        body=_receipt_body(
            number=41,
            branch="feat/earlier",
            base="9" * 40,
            head=OTHER_HEAD,
        ),
    )
    candidate = _pr(42, branch="feat/exact-pr")
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(malformed, candidate),
        checks={
            41: _check(CheckStatus.SUCCESS, head=OTHER_HEAD),
            42: _check(CheckStatus.SUCCESS),
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


def test_reanchor_lifecycle_accepts_current_pr_base_after_publication_observation() -> (
    None
):
    candidate = _pr(42, branch="feat/exact-pr", base=LIVE)
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate,),
        checks={42: _check(CheckStatus.SUCCESS)},
    )

    proof = verify_reanchor_lifecycle(
        github,
        pull_request_number=42,
        branch="feat/exact-pr",
        expected_pr_base_sha=LIVE,
        expected_remote_head=HEAD,
        live_main_sha=LIVE,
    )

    assert proof.pull_request_number == 42
    assert proof.base_sha == LIVE
    assert proof.required_status is CheckStatus.SUCCESS


def test_reanchor_lifecycle_accepts_valid_typed_base_lag_after_pr_base_advances() -> (
    None
):
    candidate = _pr(
        42,
        branch="feat/exact-pr",
        base=LIVE,
        body=_receipt_body(
            number=42,
            branch="feat/exact-pr",
            base=BASE,
            head=HEAD,
        ),
    )
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate,),
        checks={42: _check(CheckStatus.SUCCESS)},
    )

    proof = verify_reanchor_lifecycle(
        github,
        pull_request_number=42,
        branch="feat/exact-pr",
        expected_pr_base_sha=LIVE,
        expected_remote_head=HEAD,
        live_main_sha=LIVE,
    )

    assert proof.pull_request_number == 42
    assert proof.base_sha == LIVE
    assert proof.required_status is CheckStatus.SUCCESS


def test_reanchor_lifecycle_accepts_typed_base_lag_before_current_main_reanchor() -> (
    None
):
    candidate = _pr(
        42,
        branch="feat/exact-pr",
        base=BASE,
        body=_receipt_body(
            number=42,
            branch="feat/exact-pr",
            base=LIVE,
            head=HEAD,
        ),
    )
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate,),
        checks={42: _check(CheckStatus.SUCCESS)},
    )

    proof = verify_reanchor_lifecycle(
        github,
        pull_request_number=42,
        branch="feat/exact-pr",
        expected_pr_base_sha=BASE,
        expected_remote_head=HEAD,
        live_main_sha=LIVE,
    )

    assert proof.pull_request_number == 42
    assert proof.base_sha == BASE
    assert proof.required_status is CheckStatus.SUCCESS


def test_reanchor_lifecycle_rejects_typed_base_lag_for_legacy_contract() -> None:
    candidate = _pr(
        42,
        branch="feat/exact-pr",
        base=BASE,
        body=_receipt_body(
            number=42,
            branch="feat/exact-pr",
            base=LIVE,
            head=HEAD,
        ),
    )
    github = FakeGitHub(
        all_for_branch=(candidate,),
        open_prs=(candidate,),
        checks={42: _check(CheckStatus.SUCCESS)},
    )

    with pytest.raises(ReanchorRefused, match="no required-green unheld merge-front"):
        verify_reanchor_lifecycle(
            github,
            pull_request_number=42,
            branch="feat/exact-pr",
            expected_base_sha=BASE,
            expected_remote_head=HEAD,
            live_main_sha=LIVE,
        )


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
        (
            _pr(42, branch="feat/exact-pr", base=LIVE),
            _check(CheckStatus.SUCCESS),
            "stale",
        ),
        (
            _pr(42, branch="feat/exact-pr", draft=True),
            _check(CheckStatus.SUCCESS),
            "draft",
        ),
        (
            _pr(42, branch="feat/exact-pr", mergeable=False),
            _check(CheckStatus.SUCCESS),
            "mergeable",
        ),
        (
            _pr(42, branch="feat/exact-pr"),
            _check(CheckStatus.FAILURE),
            "required-green",
        ),
        (
            _pr(42, branch="feat/exact-pr"),
            _check(CheckStatus.ABSENT, names=()),
            "required code context",
        ),
        (
            _pr(42, branch="feat/exact-pr"),
            _check(
                CheckStatus.SUCCESS,
                names=("agent-review", "required", "unexpected"),
            ),
            "required code context",
        ),
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
