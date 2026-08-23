from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.branch_content import BranchContentEvidence  # noqa: E402
from delivery_control.domain.errors import PolicyViolation  # noqa: E402
from delivery_control.domain.observations import (  # noqa: E402
    CanonicalCheckoutSnapshot,
    InventoryProblem,
    PhysicalWorktree,
    PullRequestInventory,
    RegistryInventory,
)
from delivery_control.services.unregistered_branch import (  # noqa: E402
    UnregisteredBranchDiscardService,
)

BASE = "a" * 40
HEAD = "b" * 40
FINGERPRINT = "c" * 64
BRANCH = "feat/unlanded"


class FakeRegistry:
    def __init__(self, inventory: RegistryInventory | None = None) -> None:
        self.inventory = inventory or RegistryInventory(())

    def list_records(self) -> RegistryInventory:
        return self.inventory


class FakeGit:
    def __init__(self) -> None:
        self.local = HEAD
        self.deleted = False
        self.content = BranchContentEvidence(
            schema="kg.delivery.branch-content.v1",
            branch=BRANCH,
            base_sha=BASE,
            head_sha=HEAD,
            base_is_ancestor=False,
            ahead_commit_count=2,
            behind_commit_count=1,
            changed_paths=("ops/example.py",),
            change_fingerprint=FINGERPRINT,
            commit_subjects=("unlanded change",),
            commit_subjects_truncated=False,
            complete=True,
        )

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(Path("/repo"), "main", BASE, True)

    def origin_main_sha(self) -> str:
        return BASE

    def local_branch_sha(self, branch: str) -> str | None:
        return None if self.deleted else self.local

    def remote_branch_sha(self, branch: str) -> str | None:
        return None

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return ()

    def inspect_branch_content(
        self,
        *,
        branch: str,
        base_sha: str,
        max_commit_summaries: int = 20,
    ) -> BranchContentEvidence:
        return self.content

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert branch == BRANCH and expected_head_sha == HEAD
        self.deleted = True


class FakeGitHub:
    def __init__(self, inventory: PullRequestInventory | None = None) -> None:
        self.inventory = inventory or PullRequestInventory(())

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return self.inventory


def _service(
    git: FakeGit,
    *,
    registry: FakeRegistry | None = None,
    github: FakeGitHub | None = None,
) -> UnregisteredBranchDiscardService:
    return UnregisteredBranchDiscardService(
        registry=registry or FakeRegistry(),
        git_query=git,
        git_content=git,
        git_command=git,
        github=github or FakeGitHub(),
    )


def test_unlanded_branch_requires_explicit_confirmation() -> None:
    git = FakeGit()

    with pytest.raises(PolicyViolation, match="explicit confirmation"):
        _service(git).discard(
            branch=BRANCH,
            expected_head_sha=HEAD,
            expected_content_fingerprint=FINGERPRINT,
            operator="supervisor",
            reason="reviewed local-only branch",
            confirm_unmerged=False,
        )

    assert not git.deleted


def test_explicit_unlanded_discard_is_exact_and_returns_proof() -> None:
    git = FakeGit()

    result = _service(git).discard(
        branch=BRANCH,
        expected_head_sha=HEAD,
        expected_content_fingerprint=FINGERPRINT,
        operator="supervisor",
        reason="reviewed local-only branch and explicitly discarded its changes",
        confirm_unmerged=True,
    )

    assert result.disposition == "unregistered_local_branch_discarded"
    assert result.unmerged_content_confirmed
    assert result.local_branch_absent
    assert len(result.proof_digest) == 64


def test_registry_source_problem_blocks_unlanded_discard() -> None:
    git = FakeGit()
    registry = FakeRegistry(
        RegistryInventory(
            records=(),
            problems=(InventoryProblem("registry", "broken", "unreadable"),),
        )
    )
    preflight = _service(git, registry=registry).preflight(
        branch=BRANCH,
        expected_head_sha=HEAD,
        allow_unmerged=True,
    )

    assert preflight.eligible is False
    assert "registry inventory has source problems" in "; ".join(preflight.blockers)


def test_unrelated_branch_scoped_registry_problem_does_not_block_exact_discard() -> (
    None
):
    git = FakeGit()
    registry = FakeRegistry(
        RegistryInventory(
            records=(),
            problems=(
                InventoryProblem(
                    "registry",
                    "feat/other",
                    "unreadable",
                    identity_kind="branch",
                ),
            ),
        )
    )

    preflight = _service(git, registry=registry).preflight(
        branch=BRANCH,
        expected_head_sha=HEAD,
        allow_unmerged=True,
    )

    assert preflight.eligible
