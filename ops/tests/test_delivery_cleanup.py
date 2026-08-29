from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import CompareAndSwapConflict, PolicyViolation
from delivery_control.domain.models import HandbackReceipt, Scope
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    FileChange,
    FileOperation,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.domain.states import HoldKind
from delivery_control.services.cleanup import CleanupService
from delivery_control.services.pr_contract import render_pull_request_body
from delivery_control.services.sync_main import MainSyncService

BASE = "a" * 40
HEAD = "b" * 40
BRANCH = "feat/cleanup"
PATH = Path("/tmp/cleanup")


def _receipt() -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="DIRECT-1",
        owner_thread_id="thread-1",
        claim_generation=2,
        branch=BRANCH,
        worktree_path=str(PATH),
        base_sha=BASE,
        parent_sha=BASE,
        head_sha=HEAD,
        origin_main_sha=BASE,
        content_digest="c" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


def _record(receipt: HandbackReceipt, *, status: str = "active") -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id=receipt.lane_id,
        branch=receipt.branch,
        path=Path(receipt.worktree_path),
        status=status,
        scope=receipt.scope,
        base_sha=receipt.base_sha,
        claim_generation=receipt.claim_generation,
        owner_thread_id=receipt.owner_thread_id,
        handed_back_sha=receipt.head_sha,
        handback_claim_generation=receipt.claim_generation,
        handback_valid=True,
        handback_digest=receipt.content_digest,
        handback_origin_main_sha=receipt.origin_main_sha,
    )


def _snapshot(receipt: HandbackReceipt, *, clean: bool = True) -> WorktreeSnapshot:
    return WorktreeSnapshot(
        path=Path(receipt.worktree_path),
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        parent_sha=receipt.parent_sha,
        clean=clean,
        changes=(FileChange(FileOperation.MODIFY, "ops/a.py"),),
    )


def _pull_request(
    receipt: HandbackReceipt,
    *,
    state: str,
    body: str | None = None,
    labels: tuple[str, ...] = (),
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=9,
        url="https://example.test/pull/9",
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        state=state,
        draft=False,
        mergeable=True,
        title="fix: cleanup",
        body=body if body is not None else render_pull_request_body(receipt),
        labels=labels,
    )


class FakeRegistry:
    def __init__(self, record: RegistrySnapshot) -> None:
        self.record = record
        self.transitions: list[str] = []

    def list_records(self) -> RegistryInventory:
        return RegistryInventory((self.record,))

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        return self.record if self.record.lane_id == lane_id else None

    def find_exact_claim(
        self,
        *,
        lane_id: str,
        branch: str,
        path: Path,
        claim_generation: int,
    ) -> RegistrySnapshot | None:
        if (
            self.record.lane_id == lane_id
            and self.record.branch == branch
            and self.record.path == path
            and self.record.claim_generation == claim_generation
        ):
            return self.record
        return None

    def resolve(
        self,
        lane_id: str,
        disposition: str,
        *,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
        terminal_proof=None,
    ) -> None:
        assert lane_id == self.record.lane_id
        assert expected_claim_generation == self.record.claim_generation
        assert expected_branch == self.record.branch
        assert Path(expected_path) == self.record.path
        assert expected_head_sha == self.record.handed_back_sha
        if disposition == "merged":
            assert terminal_proof is not None
            assert terminal_proof.pr_number == 9
        else:
            assert terminal_proof is None
        self.transitions.append(disposition)
        self.record = replace(self.record, status=disposition)


class FakeGit:
    def __init__(
        self,
        receipt: HandbackReceipt,
        *,
        snapshot: WorktreeSnapshot | None = None,
        has_worktree: bool = True,
        local_sha: str | None = HEAD,
        remote_sha: str | None = HEAD,
        local_main: str = BASE,
        origin_main: str = BASE,
        origin_main_readbacks: tuple[str, ...] = (),
        remote_branch_readbacks: tuple[str | None, ...] = (),
        canonical_branch: str = "main",
        canonical_clean: bool = True,
        replacement_worktree_after_remove: PhysicalWorktree | None = None,
    ) -> None:
        self.snapshot = snapshot or _snapshot(receipt)
        self.worktrees = (
            (
                PhysicalWorktree(
                    Path(receipt.worktree_path), receipt.head_sha, receipt.branch
                ),
            )
            if has_worktree
            else ()
        )
        self.local_sha = local_sha
        self.remote_sha = remote_sha
        self.local_main = local_main
        self.origin_main = origin_main
        self.origin_main_readbacks = list(origin_main_readbacks)
        self.remote_branch_readbacks = list(remote_branch_readbacks)
        self.canonical_branch = canonical_branch
        self.canonical_clean = canonical_clean
        self.replacement_worktree_after_remove = replacement_worktree_after_remove
        self.actions: list[str] = []

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.worktrees

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(
            path=Path("/repo"),
            branch=self.canonical_branch,
            head_sha=self.local_main,
            clean=self.canonical_clean,
        )

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        if path == Path("/repo"):
            return WorktreeSnapshot(
                path=path,
                branch=self.canonical_branch,
                base_sha=base_sha,
                head_sha=self.local_main,
                parent_sha=self.local_main,
                clean=self.canonical_clean,
                changes=(),
            )
        return self.snapshot

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local_sha

    def remote_branch_sha(self, branch: str) -> str | None:
        if self.remote_branch_readbacks:
            self.remote_sha = self.remote_branch_readbacks.pop(0)
        return self.remote_sha

    def remove_worktree(self, path: Path, *, expected_head_sha: str) -> None:
        assert expected_head_sha == HEAD
        self.actions.append("remove-worktree")
        self.worktrees = (
            (self.replacement_worktree_after_remove,)
            if self.replacement_worktree_after_remove is not None
            else ()
        )

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert expected_head_sha == self.local_sha
        self.actions.append("delete-local")
        self.local_sha = None

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert expected_head_sha == self.remote_sha
        self.actions.append("delete-remote")
        self.remote_sha = None

    def local_main_sha(self) -> str:
        return self.local_main

    def origin_main_sha(self) -> str:
        if self.origin_main_readbacks:
            self.origin_main = self.origin_main_readbacks.pop(0)
        return self.origin_main

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        assert expected_local_sha == self.local_main
        assert expected_origin_sha == self.origin_main
        self.actions.append("sync-main")
        self.local_main = self.origin_main
        return self.local_main


class FakeGitHub:
    def __init__(
        self,
        pull_request: PullRequestSnapshot,
        receipt: HandbackReceipt,
        *,
        pull_request_readbacks: tuple[PullRequestSnapshot, ...] = (),
        changed_paths: tuple[str, ...] | None = None,
    ) -> None:
        self.pull_request = pull_request
        self.receipt = receipt
        self.pull_request_readbacks = list(pull_request_readbacks)
        self.paths = receipt.scope.paths if changed_paths is None else changed_paths

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        assert number == self.pull_request.number
        if self.pull_request_readbacks:
            self.pull_request = self.pull_request_readbacks.pop(0)
        return self.pull_request

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return self.paths


def _service(
    receipt: HandbackReceipt,
    *,
    registry: FakeRegistry,
    git: FakeGit,
    state: str,
) -> CleanupService:
    return CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(_pull_request(receipt, state=state), receipt),
    )


def test_publish_release_moves_durable_queue_to_github_and_removes_local_assets() -> (
    None
):
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt)

    result = _service(
        receipt, registry=registry, git=git, state="OPEN"
    ).release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending", "published"]
    assert git.actions == ["remove-worktree", "delete-local"]
    assert result.worktree_absent and result.local_branch_absent
    assert not result.remote_branch_absent


@pytest.mark.parametrize(
    ("canonical_branch", "canonical_clean", "message"),
    (
        ("debug/feature", True, "canonical checkout must be on main"),
        ("main", False, "canonical checkout is dirty"),
    ),
)
def test_publish_release_refuses_before_claim_lease_without_canonical_main(
    canonical_branch: str, canonical_clean: bool, message: str
) -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(
        receipt,
        canonical_branch=canonical_branch,
        canonical_clean=canonical_clean,
    )

    with pytest.raises(PolicyViolation, match=message):
        _service(
            receipt, registry=registry, git=git, state="OPEN"
        ).release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == []
    assert git.actions == []


@pytest.mark.parametrize(
    ("body", "labels"),
    (
        (
            render_pull_request_body(_receipt(), holds=frozenset({HoldKind.SECURITY})),
            (),
        ),
        (render_pull_request_body(_receipt()), ("delivery-hold:security",)),
        (render_pull_request_body(_receipt()) + "\nPUBLISH ONLY\n", ()),
    ),
    ids=("typed-hold", "label-hold", "legacy-hold"),
)
def test_publish_release_preserves_holds_while_releasing_local_assets(
    body: str, labels: tuple[str, ...]
) -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt)
    pull_request = _pull_request(
        receipt,
        state="OPEN",
        body=body,
        labels=labels,
    )
    service = CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(pull_request, receipt),
    )

    result = service.release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending", "published"]
    assert result.worktree_absent and result.local_branch_absent


def test_publish_release_blocks_dirty_worktree_before_releasing_claim() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt, snapshot=_snapshot(receipt, clean=False))

    with pytest.raises(PolicyViolation, match="worktree changed"):
        _service(
            receipt, registry=registry, git=git, state="OPEN"
        ).release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == []
    assert git.actions == []


def test_publish_release_retry_is_idempotent_after_local_assets_are_absent() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt, status="published"))
    git = FakeGit(receipt, has_worktree=False, local_sha=None)

    result = _service(
        receipt, registry=registry, git=git, state="OPEN"
    ).release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == []
    assert git.actions == []
    assert result.worktree_absent and result.local_branch_absent


def test_publish_release_accepts_actual_changed_paths_as_scope_subset() -> None:
    receipt = replace(
        _receipt(),
        scope=Scope.from_paths(modify=("ops/a.py", "ops/b.py")),
    )
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt)
    service = CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(
            _pull_request(receipt, state="OPEN"),
            receipt,
            changed_paths=("ops/a.py",),
        ),
    )

    result = service.release_after_publish(receipt=receipt, pull_request_number=9)

    assert result.worktree_absent and result.local_branch_absent


def test_merged_cleanup_removes_exact_remote_and_terminalizes_registry() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt, status="published"))
    git = FakeGit(receipt, has_worktree=False, local_sha=None)

    result = _service(
        receipt, registry=registry, git=git, state="MERGED"
    ).finalize_merged(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending", "merged"]
    assert git.actions == ["delete-remote"]
    assert result.remote_branch_absent


def test_cleanup_refuses_remote_drift() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt, remote_sha="d" * 40)

    with pytest.raises(PolicyViolation, match="remote branch"):
        _service(
            receipt, registry=registry, git=git, state="OPEN"
        ).release_after_publish(receipt=receipt, pull_request_number=9)
    assert not git.actions


@pytest.mark.parametrize("state", ("OPEN", "MERGED"))
def test_cleanup_refuses_pr_retargeted_away_from_main(state: str) -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt)
    pull_request = replace(
        _pull_request(receipt, state=state),
        base_branch="release",
    )
    service = CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(pull_request, receipt),
    )

    with pytest.raises(PolicyViolation, match="exact handback"):
        if state == "OPEN":
            service.release_after_publish(receipt=receipt, pull_request_number=9)
        else:
            service.finalize_merged(receipt=receipt, pull_request_number=9)

    assert registry.transitions == []
    assert git.actions == []


@pytest.mark.parametrize("state", ("OPEN", "MERGED"))
def test_cleanup_rechecks_pr_after_lease_before_deleting_local_assets(
    state: str,
) -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt)
    exact = _pull_request(receipt, state=state)
    retargeted = replace(exact, base_branch="release")
    service = CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(
            exact,
            receipt,
            pull_request_readbacks=(exact, retargeted),
        ),
    )

    with pytest.raises(PolicyViolation, match="exact handback"):
        if state == "OPEN":
            service.release_after_publish(receipt=receipt, pull_request_number=9)
        else:
            service.finalize_merged(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending"]
    assert registry.record.status == "cleanup_pending"
    assert git.actions == []
    assert git.worktrees and git.local_sha == HEAD and git.remote_sha == HEAD


def test_publish_release_rechecks_pr_before_terminal_disposition() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt)
    exact = _pull_request(receipt, state="OPEN")
    retargeted = replace(exact, base_branch="release")
    service = CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(
            exact,
            receipt,
            pull_request_readbacks=(exact, exact, exact, retargeted),
        ),
    )

    with pytest.raises(PolicyViolation, match="exact handback"):
        service.release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending"]
    assert registry.record.status == "cleanup_pending"
    assert git.actions == ["remove-worktree", "delete-local"]
    assert git.remote_sha == HEAD


def test_publish_release_fails_closed_when_remote_branch_disappears_before_terminal_cas() -> (
    None
):
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt, remote_branch_readbacks=(HEAD, None))

    with pytest.raises(PolicyViolation, match="remote branch"):
        _service(
            receipt, registry=registry, git=git, state="OPEN"
        ).release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending"]
    assert registry.record.status == "cleanup_pending"
    assert git.actions == ["remove-worktree", "delete-local"]
    assert git.remote_sha is None


def test_merged_cleanup_rechecks_pr_before_remote_delete() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt, status="published"))
    git = FakeGit(receipt, has_worktree=False, local_sha=None)
    exact = _pull_request(receipt, state="MERGED")
    retargeted = replace(exact, base_branch="release")
    service = CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(
            exact,
            receipt,
            pull_request_readbacks=(exact, exact, retargeted),
        ),
    )

    with pytest.raises(PolicyViolation, match="exact handback"):
        service.finalize_merged(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending"]
    assert registry.record.status == "cleanup_pending"
    assert git.actions == []
    assert git.remote_sha == HEAD


def test_merged_cleanup_rechecks_pr_before_terminal_disposition() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt, status="published"))
    git = FakeGit(receipt, has_worktree=False, local_sha=None)
    exact = _pull_request(receipt, state="MERGED")
    retargeted = replace(exact, base_branch="release")
    service = CleanupService(
        registry_query=registry,
        registry_command=registry,
        git_query=git,
        git_command=git,
        github=FakeGitHub(
            exact,
            receipt,
            pull_request_readbacks=(exact, exact, exact, retargeted),
        ),
    )

    with pytest.raises(PolicyViolation, match="exact handback"):
        service.finalize_merged(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending"]
    assert registry.record.status == "cleanup_pending"
    assert git.actions == ["delete-remote"]


@pytest.mark.parametrize(
    "worktrees",
    (
        (PhysicalWorktree(PATH, HEAD, "feat/rebound"),),
        (PhysicalWorktree(Path("/tmp/other"), HEAD, BRANCH),),
        (
            PhysicalWorktree(PATH, HEAD, BRANCH),
            PhysicalWorktree(PATH, HEAD, BRANCH),
        ),
    ),
    ids=("sealed-path-branch-drift", "sealed-branch-path-drift", "duplicate-match"),
)
def test_cleanup_refuses_non_unique_sealed_path_branch_binding(
    worktrees: tuple[PhysicalWorktree, ...],
) -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    git = FakeGit(receipt)
    git.worktrees = worktrees

    with pytest.raises(PolicyViolation, match="sealed worktree path and branch"):
        _service(
            receipt, registry=registry, git=git, state="OPEN"
        ).release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == []
    assert git.actions == []


def test_cleanup_result_readback_refuses_rebound_sealed_path() -> None:
    receipt = _receipt()
    registry = FakeRegistry(_record(receipt))
    rebound = PhysicalWorktree(PATH, HEAD, "feat/rebound")
    git = FakeGit(receipt, replacement_worktree_after_remove=rebound)

    with pytest.raises(PolicyViolation, match="sealed worktree path and branch"):
        _service(
            receipt, registry=registry, git=git, state="OPEN"
        ).release_after_publish(receipt=receipt, pull_request_number=9)

    assert registry.transitions == ["cleanup_pending", "published"]
    assert git.actions == ["remove-worktree", "delete-local"]


def test_main_sync_is_noop_when_exact_and_ff_only_when_behind() -> None:
    receipt = _receipt()
    exact = FakeGit(receipt)
    behind = FakeGit(receipt, local_main="c" * 40, origin_main="d" * 40)

    exact_result = MainSyncService(
        canonical_path=Path("/repo"), query=exact, command=exact
    ).sync()
    behind_result = MainSyncService(
        canonical_path=Path("/repo"), query=behind, command=behind
    ).sync()

    assert not exact_result.changed
    assert exact.actions == []
    assert behind_result.changed
    assert behind_result.after_sha == "d" * 40
    assert behind.actions == ["sync-main"]


def test_main_sync_noop_refuses_fresh_origin_main_drift() -> None:
    drifted_origin = "d" * 40
    git = FakeGit(
        _receipt(),
        origin_main_readbacks=(BASE, drifted_origin),
    )

    with pytest.raises(CompareAndSwapConflict, match="origin/main changed"):
        MainSyncService(canonical_path=Path("/repo"), query=git, command=git).sync()

    assert git.actions == []


def test_main_sync_fast_forward_refuses_fresh_origin_main_drift() -> None:
    expected_origin = "d" * 40
    drifted_origin = "e" * 40
    git = FakeGit(
        _receipt(),
        local_main="c" * 40,
        origin_main=expected_origin,
        origin_main_readbacks=(expected_origin, drifted_origin),
    )

    with pytest.raises(CompareAndSwapConflict, match="origin/main changed"):
        MainSyncService(canonical_path=Path("/repo"), query=git, command=git).sync()

    assert git.actions == ["sync-main"]
    assert git.local_main == expected_origin


@pytest.mark.parametrize(
    ("canonical_branch", "canonical_clean"),
    (("feat/not-main", True), ("main", False)),
)
def test_main_sync_refuses_wrong_or_dirty_canonical_checkout(
    canonical_branch: str, canonical_clean: bool
) -> None:
    git = FakeGit(
        _receipt(),
        canonical_branch=canonical_branch,
        canonical_clean=canonical_clean,
    )

    with pytest.raises(PolicyViolation, match="canonical checkout"):
        MainSyncService(canonical_path=Path("/repo"), query=git, command=git).sync()
