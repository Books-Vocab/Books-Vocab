from __future__ import annotations

import sys
from dataclasses import replace
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
from worktree_reanchor_core import resume_transaction
from worktree_reanchor_core.domain import RegistryPreflight
from worktree_reanchor_core.errors import ReanchorRefused
from worktree_reanchor_core.lifecycle_proof import (
    verify_resume_lifecycle,
)
from worktree_reanchor_core.resume_domain import (
    build_request,
    verify_merged_maintenance_lifecycle,
)

BASE = "1" * 40
HEAD = "3" * 40
PARENT = "2" * 40
LANE = "DIRECT-MERGED-MAINTENANCE"
BRANCH = "debug/merged-maintenance"
OWNER = "owner-thread"
DIGEST = "4" * 64
SCOPE = Scope.from_paths(modify=("docs/runbook/system.md",))


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


def _merged_pr(*, body: str | None = None) -> PullRequestSnapshot:
    receipt = HandbackReceipt(
        lane_id=LANE,
        owner_thread_id=OWNER,
        claim_generation=0,
        branch=BRANCH,
        worktree_path="/tmp/merged-maintenance-source",
        base_sha=BASE,
        parent_sha=PARENT,
        head_sha=HEAD,
        origin_main_sha=BASE,
        content_digest=DIGEST,
        scope=SCOPE,
    )
    return PullRequestSnapshot(
        number=1591,
        url="https://example.test/pull/1591",
        branch=BRANCH,
        base_sha=BASE,
        head_sha=HEAD,
        state="MERGED",
        draft=False,
        mergeable=True,
        base_branch="main",
        node_id="PR_1591",
        merged_at=datetime(2026, 8, 25, tzinfo=UTC),
        body=body if body is not None else render_pull_request_body(receipt),
    )


def _check(status: CheckStatus) -> CheckSnapshot:
    return CheckSnapshot(
        status=status,
        head_sha=HEAD,
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
        names=("required",),
    )


def _absent_check() -> CheckSnapshot:
    return CheckSnapshot(
        status=CheckStatus.ABSENT,
        head_sha=HEAD,
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
        names=(),
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


def test_maintenance_resume_accepts_exact_required_absence_observation() -> None:
    absent = CheckSnapshot(
        status=CheckStatus.ABSENT,
        head_sha=HEAD,
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
        names=(),
    )

    proof = verify_resume_lifecycle(
        FakeGitHub(absent),
        branch="debug/delivery-observation-batch-20260823",
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
        require_failed=False,
        allow_missing_required=True,
    )

    assert proof.required_status is CheckStatus.ABSENT


@pytest.mark.parametrize(
    "check",
    [_check(CheckStatus.SUCCESS), _absent_check()],
    ids=["required-success", "required-absent"],
)
def test_perform_resume_allows_same_head_maintenance_for_open_pr(
    check: CheckSnapshot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _pr()
    github = FakeGitHub(check)
    github.all_for_branch = (candidate,)
    preflight = RegistryPreflight(
        original={
            "base": BASE,
            "base_sha": BASE,
            "path": str(tmp_path / "released"),
        },
        fingerprint="fingerprint",
        base_sha=BASE,
        published_base_sha=BASE,
        declared=(("docs/runbook/system.md", "modify"),),
    )

    monkeypatch.setattr(
        resume_transaction.git_ops, "validate_repository", lambda _: None
    )
    monkeypatch.setattr(
        resume_transaction.git_ops, "_git", lambda *_args, **_kwargs: (0, "")
    )
    monkeypatch.setattr(
        resume_transaction.registry_ops,
        "preflight_resume",
        lambda **_: preflight,
    )
    monkeypatch.setattr(
        resume_transaction.lifecycle_proof,
        "build_github",
        lambda *_args, **_kwargs: github,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "validate_released_assets",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "ensure_exact_source",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "provision_exact",
        lambda *_args, **_kwargs: HEAD,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "verify_remote_head",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resume_transaction.registry_ops,
        "register_resumed",
        lambda **_: {"claim_generation": 1},
    )

    payload = resume_transaction.perform_resume(
        repo=tmp_path,
        state_path=tmp_path / "registry.json",
        lane_id="DIRECT-TEST",
        branch=candidate.branch,
        owner_thread_id="owner-thread",
        claim_generation=0,
        expected_remote_head=HEAD,
        target=tmp_path / "target",
        previous_handback=HEAD,
        mode="maintenance",
    )

    assert payload["status"] == "ready-for-owner-fix"
    assert payload["mode"] == "maintenance"
    assert payload["head"] == HEAD


def test_perform_resume_uses_published_pr_base_for_lifecycle_readback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    published_base = "5" * 40
    github = FakeGitHub(_check(CheckStatus.FAILURE))
    github.pr = replace(github.pr, base_sha=published_base)
    preflight = RegistryPreflight(
        original={
            "base": BASE,
            "base_sha": BASE,
            "path": str(tmp_path / "released"),
        },
        fingerprint="fingerprint",
        base_sha=BASE,
        published_base_sha=published_base,
        declared=(("docs/runbook/system.md", "modify"),),
    )

    monkeypatch.setattr(
        resume_transaction.git_ops, "validate_repository", lambda _: None
    )
    monkeypatch.setattr(
        resume_transaction.git_ops, "_git", lambda *_args, **_kwargs: (0, "")
    )
    monkeypatch.setattr(
        resume_transaction.registry_ops,
        "preflight_resume",
        lambda **_: preflight,
    )
    monkeypatch.setattr(
        resume_transaction.lifecycle_proof,
        "build_github",
        lambda *_args, **_kwargs: github,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "validate_released_assets",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "ensure_exact_source",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "provision_exact",
        lambda *_args, **_kwargs: HEAD,
    )
    monkeypatch.setattr(
        resume_transaction.resume_git_ops,
        "verify_remote_head",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resume_transaction.registry_ops,
        "register_resumed",
        lambda **_: {"claim_generation": 1},
    )

    payload = resume_transaction.perform_resume(
        repo=tmp_path,
        state_path=tmp_path / "registry.json",
        lane_id="DIRECT-TEST",
        branch=github.pr.branch,
        owner_thread_id="owner-thread",
        claim_generation=0,
        expected_remote_head=HEAD,
        target=tmp_path / "target",
        previous_handback=HEAD,
        mode="maintenance",
    )

    assert payload["status"] == "ready-for-owner-fix"
    assert payload["head"] == HEAD


def test_merged_maintenance_accepts_only_exact_typed_proof() -> None:
    proof = verify_merged_maintenance_lifecycle(
        _merged_pr(),
        lane_id=LANE,
        branch=BRANCH,
        owner_thread_id=OWNER,
        claim_generation=0,
        expected_remote_head=HEAD,
        previous_handback=HEAD,
        recorded_base_sha=BASE,
        published_base_sha=BASE,
        source_parent_sha=PARENT,
        declared_scope=(("docs/runbook/system.md", "modify"),),
        handback_digest=DIGEST,
    )

    assert proof.action == "reconcile-merged-maintenance"
    assert proof.verdict == "terminal-reconciliation-ready"
    assert proof.pr_number == 1591
    assert proof.head_sha == HEAD


def test_merged_maintenance_missing_typed_proof_is_blocked() -> None:
    with pytest.raises(ReanchorRefused, match="typed delivery receipt"):
        verify_merged_maintenance_lifecycle(
            _merged_pr(body="merged without receipt"),
            lane_id=LANE,
            branch=BRANCH,
            owner_thread_id=OWNER,
            claim_generation=0,
            expected_remote_head=HEAD,
            previous_handback=HEAD,
            recorded_base_sha=BASE,
            published_base_sha=BASE,
            source_parent_sha=PARENT,
            declared_scope=(("docs/runbook/system.md", "modify"),),
            handback_digest=DIGEST,
        )


def test_same_head_required_failure_resume_remains_blocked(tmp_path: Path) -> None:
    with pytest.raises(ReanchorRefused, match="different current remote HEAD"):
        build_request(
            repo=tmp_path,
            state_path=tmp_path / "registry.json",
            lane_id="DIRECT-TEST",
            branch="feat/test",
            owner_thread_id="owner",
            claim_generation=0,
            expected_remote_head=HEAD,
            previous_handback=HEAD,
            target=tmp_path / "worktree",
            mode="required-failure",
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
