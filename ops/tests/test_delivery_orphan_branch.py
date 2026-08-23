from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import DeliverySourceError, PolicyViolation
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    PhysicalWorktree,
    PullRequestInventory,
    RegistryInventory,
    RegistrySnapshot,
)
from delivery_control.services.orphan_branch import OrphanBranchDiscardService

BASE = "a" * 40
HEAD = "b" * 40
BRANCH = "feat/orphan"
PATH = Path("/tmp/orphan")


class FakeRegistry:
    def __init__(self, inventory: RegistryInventory | None = None) -> None:
        self.inventory = inventory or RegistryInventory(())

    def list_records(self) -> RegistryInventory:
        return self.inventory


class FakeGit:
    def __init__(
        self,
        *,
        local: str | None = HEAD,
        remote: str | None = None,
        physical: tuple[PhysicalWorktree, ...] = (),
        canonical_branch: str = "main",
        canonical_head: str = BASE,
        canonical_clean: bool = True,
        origin: str = BASE,
        ancestor: bool = True,
        failure: str | None = None,
    ) -> None:
        self.local = local
        self.remote = remote
        self.physical = physical
        self.canonical_branch = canonical_branch
        self.canonical_head = canonical_head
        self.canonical_clean = canonical_clean
        self.origin = origin
        self.ancestor = ancestor
        self.failure = failure
        self.actions: list[str] = []

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(
            Path("/repo"),
            self.canonical_branch,
            self.canonical_head,
            self.canonical_clean,
        )

    def origin_main_sha(self) -> str:
        return self.origin

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.physical

    def local_branch_sha(self, branch: str) -> str | None:
        if self.failure == "local":
            raise DeliverySourceError("local ref unavailable")
        return self.local

    def remote_branch_sha(self, branch: str) -> str | None:
        if self.failure == "remote":
            raise DeliverySourceError("remote ref unavailable")
        return self.remote

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        if self.failure == "ancestor":
            raise DeliverySourceError("ancestor query unavailable")
        return self.ancestor

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert expected_head_sha == HEAD
        self.actions.append("delete-local")
        self.local = None


class FakeGitHub:
    def __init__(self, inventory: PullRequestInventory | None = None) -> None:
        self.inventory = inventory or PullRequestInventory(())
        self.calls = 0

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        self.calls += 1
        return self.inventory


def _build_service(
    *,
    git: FakeGit,
    registry: FakeRegistry | None = None,
    github: FakeGitHub | None = None,
) -> OrphanBranchDiscardService:
    return OrphanBranchDiscardService(
        registry=registry or FakeRegistry(),
        git_query=git,
        git_command=git,
        github=github or FakeGitHub(),
    )


def test_discards_unregistered_local_branch_already_in_main() -> None:
    git = FakeGit()

    result = _build_service(git=git).discard(
        branch=BRANCH,
        expected_head_sha=HEAD,
        operator="supervisor",
        reason="exact ancestor orphan with no owner or PR",
    )

    assert result.disposition == "orphan_local_discarded"
    assert result.main_sha == BASE
    assert result.local_branch_absent and result.remote_branch_absent
    assert result.worktree_absent
    assert len(result.proof_digest) == 64
    assert git.actions == ["delete-local"]


def test_preflight_is_read_only_and_reports_all_passed_checks() -> None:
    git = FakeGit()

    result = _build_service(git=git).preflight(
        branch=BRANCH,
        expected_head_sha=HEAD,
    )

    assert result.schema == "kg.delivery.orphan-branch-preflight.v1"
    assert result.eligible
    assert result.main_sha == BASE
    assert result.blockers == ()
    assert len(result.passed_checks) == 7
    assert git.actions == []


def test_preflight_uses_branch_history_snapshot_without_querying_per_branch() -> None:
    github = FakeGitHub()
    result = _build_service(git=FakeGit(), github=github).preflight(
        branch=BRANCH,
        expected_head_sha=HEAD,
        pr_history=PullRequestInventory(()),
    )

    assert result.eligible
    assert github.calls == 0


def test_preflight_reports_blocker_without_deleting() -> None:
    git = FakeGit(remote=HEAD, ancestor=False)

    result = _build_service(git=git).preflight(
        branch=BRANCH,
        expected_head_sha=HEAD,
    )

    assert result.eligible is False
    assert "remote ref" in "; ".join(result.blockers)
    assert "ancestor" in "; ".join(result.blockers)
    assert git.actions == []


@pytest.mark.parametrize(
    ("failure", "message"),
    (
        ("local", "local branch HEAD query failed"),
        ("remote", "remote branch query failed"),
        ("ancestor", "ancestor query failed"),
    ),
)
def test_preflight_fails_closed_when_git_evidence_is_unavailable(
    failure: str, message: str
) -> None:
    result = _build_service(git=FakeGit(failure=failure)).preflight(
        branch=BRANCH,
        expected_head_sha=HEAD,
    )

    assert result.eligible is False
    assert message in "; ".join(result.blockers)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("canonical_branch", "feat/other", "canonical checkout must be on main"),
        ("canonical_clean", False, "canonical checkout is dirty"),
        ("canonical_head", HEAD, "canonical main is not equal"),
        ("origin", HEAD, "canonical main is not equal"),
        ("ancestor", False, "not an ancestor"),
    ),
)
def test_refuses_when_main_or_ancestry_proof_is_not_exact(
    field: str, value: object, message: str
) -> None:
    git = FakeGit(**{field: value})  # type: ignore[arg-type]

    with pytest.raises(PolicyViolation, match=message):
        _build_service(git=git).discard(
            branch=BRANCH,
            expected_head_sha=HEAD,
            operator="supervisor",
            reason="test",
        )
    assert git.actions == []


def test_refuses_registry_claim_pr_history_worktree_remote_and_missing_ref() -> None:
    claim = RegistrySnapshot(
        lane_id="LANE",
        branch=BRANCH,
        path=PATH,
        status="abandoned",
        scope=Scope.from_paths(modify=("ops/example.py",)),
        base_sha=BASE,
        claim_generation=0,
    )
    cases = (
        (
            FakeRegistry(RegistryInventory((claim,))),
            FakeGit(),
            FakeGitHub(),
            "registry claim",
        ),
        (
            FakeRegistry(),
            FakeGit(),
            FakeGitHub(PullRequestInventory((object(),))),
            "PR history",
        ),
        (
            FakeRegistry(),
            FakeGit(physical=(PhysicalWorktree(PATH, HEAD, BRANCH),)),
            FakeGitHub(),
            "physical worktree",
        ),
        (FakeRegistry(), FakeGit(remote=HEAD), FakeGitHub(), "remote ref"),
        (FakeRegistry(), FakeGit(local=None), FakeGitHub(), "absent"),
    )

    for registry, git, github, message in cases:
        with pytest.raises(PolicyViolation, match=message):
            _build_service(git=git, registry=registry, github=github).discard(
                branch=BRANCH,
                expected_head_sha=HEAD,
                operator="supervisor",
                reason="test",
            )
        assert git.actions == []
