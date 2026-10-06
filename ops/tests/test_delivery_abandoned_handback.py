from __future__ import annotations

from pathlib import Path
import sys

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.services.abandoned_handback import (
    AbandonedHandbackDiscardService,
)

BASE = "a" * 40
HEAD = "b" * 40
BRANCH = "feat/abandoned-handback"
PATH = Path("/tmp/abandoned-handback")
SCOPE = Scope.from_paths(modify=("ops/example.py",))


def _record(*, owner_thread_id: str | None = None) -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id="DIRECT-1",
        branch=BRANCH,
        path=PATH,
        status="abandoned",
        scope=SCOPE,
        base_sha=BASE,
        claim_generation=2,
        owner_thread_id=owner_thread_id,
        handed_back_sha=HEAD,
        handback_valid=True,
        handback_digest="c" * 64,
    )


class FakeRegistry:
    def __init__(self, record: RegistrySnapshot) -> None:
        self.record = record
        self.calls: list[dict[str, object]] = []

    def find_terminal_claim(self, *, branch: str) -> RegistrySnapshot | None:
        return self.record if branch == self.record.branch else None

    def discard(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class FakeGit:
    def __init__(
        self,
        *,
        local: str | None = HEAD,
        remote: str | None = HEAD,
        physical: tuple[PhysicalWorktree, ...] = (),
        canonical_branch: str = "main",
        canonical_clean: bool = True,
    ) -> None:
        self.local = local
        self.remote = remote
        self.physical = physical
        self.canonical_branch = canonical_branch
        self.canonical_clean = canonical_clean
        self.actions: list[str] = []

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(
            path=Path("/repo"),
            branch=self.canonical_branch,
            head_sha=BASE,
            clean=self.canonical_clean,
        )

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.physical

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert expected_head_sha == HEAD
        self.actions.append("delete-local")
        self.local = None

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert expected_head_sha == HEAD
        self.actions.append("delete-remote")
        self.remote = None


class FakeGitHub:
    def __init__(self, records: tuple[PullRequestSnapshot, ...] = ()) -> None:
        self.records = records

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory(self.records)


def _service(
    record: RegistrySnapshot,
    git: FakeGit,
    github: FakeGitHub | None = None,
) -> tuple[AbandonedHandbackDiscardService, FakeRegistry]:
    registry = FakeRegistry(record)
    return (
        AbandonedHandbackDiscardService(
            registry_query=registry,
            registry_command=registry,
            git_query=git,
            git_command=git,
            github=github or FakeGitHub(),
        ),
        registry,
    )


def test_ownerless_clean_handback_discard_removes_exact_refs() -> None:
    git = FakeGit()
    service, registry = _service(_record(), git)

    result = service.discard(
        branch=BRANCH,
        expected_head_sha=HEAD,
        operator="supervisor",
        reason="ownerless clean handback explicitly discarded",
    )

    assert result.disposition == "abandoned_handback_discarded"
    assert result.worktree_absent
    assert result.local_branch_absent and result.remote_branch_absent
    assert git.actions == ["delete-local", "delete-remote"]
    assert registry.calls[0]["expected_head_sha"] == HEAD


@pytest.mark.parametrize(
    ("record", "git", "github", "message"),
    (
        (
            _record(owner_thread_id="owner"),
            FakeGit(),
            FakeGitHub(),
            "still has an owner",
        ),
        (
            _record(),
            FakeGit(physical=(PhysicalWorktree(PATH, HEAD, BRANCH),)),
            FakeGitHub(),
            "physical worktree",
        ),
        (_record(), FakeGit(remote="d" * 40), FakeGitHub(), "remote branch changed"),
    ),
)
def test_discard_preserves_non_discardable_lanes(
    record: RegistrySnapshot,
    git: FakeGit,
    github: FakeGitHub,
    message: str,
) -> None:
    service, registry = _service(record, git, github)

    with pytest.raises(PolicyViolation, match=message):
        service.discard(
            branch=BRANCH,
            expected_head_sha=HEAD,
            operator="supervisor",
            reason="discard attempt",
        )

    assert registry.calls == []
    assert git.actions == []


def test_discard_refuses_pr_history_before_any_mutation() -> None:
    pr = PullRequestSnapshot(
        number=42,
        url="https://example.test/pull/42",
        branch=BRANCH,
        base_sha=BASE,
        head_sha=HEAD,
        state="CLOSED",
        draft=False,
        mergeable=True,
    )
    git = FakeGit()
    service, registry = _service(_record(), git, FakeGitHub((pr,)))

    with pytest.raises(PolicyViolation, match="PR history"):
        service.discard(
            branch=BRANCH,
            expected_head_sha=HEAD,
            operator="supervisor",
            reason="discard attempt",
        )

    assert registry.calls == []
    assert git.actions == []
