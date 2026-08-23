from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.branch_lifecycle import (  # noqa: E402
    BranchCleanupAction,
    BranchDisposition,
    BranchSide,
)
from delivery_control.domain.candidate_issues import CandidateIssueInventory  # noqa: E402
from delivery_control.domain.branch_refs import BranchInventory  # noqa: E402
from delivery_control.domain.observations import (  # noqa: E402
    PhysicalWorktree,
    PullRequestInventory,
    RegistryInventory,
    WorktreeSnapshot,
)
from delivery_control.services.inspect import InspectService  # noqa: E402


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


class FakeRegistry:
    def list_records(self) -> RegistryInventory:
        return RegistryInventory(())


class FakeGit:
    def __init__(
        self,
        *,
        local_ref: tuple[str, str] = (
            "feat/add-link-enrich-operation-20260820",
            SHA_B,
        ),
        physical: tuple[PhysicalWorktree, ...] = (),
        snapshots: dict[Path, WorktreeSnapshot] | None = None,
    ) -> None:
        self.inventory = BranchInventory(
            local=(local_ref,),
            remote=(("debug/remote-orphan", SHA_C),),
        )
        self.physical = physical
        self.snapshots = snapshots or {}

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.physical

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        return self.snapshots[path]

    def branch_inventory(self) -> BranchInventory:
        return self.inventory

    def local_main_sha(self) -> str:
        return SHA_A

    def origin_main_sha(self) -> str:
        return SHA_A


class FakeGitHub:
    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory((), ())

    def list_open_candidate_issues(self) -> CandidateIssueInventory:
        return CandidateIssueInventory((), ())


class FakeRuntime:
    pass


def test_inspect_exposes_local_and_remote_orphan_refs() -> None:
    inventory = InspectService(
        registry=FakeRegistry(),
        git=FakeGit(),
        github=FakeGitHub(),
        runtime=FakeRuntime(),
    ).inspect()

    assets = inventory.branch_lifecycle.assets

    assert {(asset.side, asset.branch) for asset in assets} == {
        (BranchSide.LOCAL, "feat/add-link-enrich-operation-20260820"),
        (BranchSide.REMOTE, "debug/remote-orphan"),
    }
    local = next(asset for asset in assets if asset.side is BranchSide.LOCAL)
    remote = next(asset for asset in assets if asset.side is BranchSide.REMOTE)
    assert local.disposition is BranchDisposition.ORPHAN_LOCAL_RECONCILE
    assert local.cleanup_action is BranchCleanupAction.RECONCILE_LOCAL_ORPHAN
    assert remote.disposition is BranchDisposition.ORPHAN_REMOTE_RECONCILE
    assert remote.cleanup_action is BranchCleanupAction.RECONCILE_REMOTE_ORPHAN


def test_inspect_preserves_dirty_physical_branch_evidence(tmp_path: Path) -> None:
    path = tmp_path / "dirty"
    git = FakeGit(
        local_ref=("feat/dirty", SHA_B),
        physical=(PhysicalWorktree(path=path, head_sha=SHA_B, branch="feat/dirty"),),
        snapshots={
            path: WorktreeSnapshot(
                path=path,
                branch="feat/dirty",
                base_sha=SHA_A,
                head_sha=SHA_B,
                parent_sha=SHA_A,
                clean=False,
                changes=(),
            )
        },
    )

    inventory = InspectService(
        registry=FakeRegistry(),
        git=git,
        github=FakeGitHub(),
        runtime=FakeRuntime(),
    ).inspect()

    asset = next(
        asset
        for asset in inventory.branch_lifecycle.assets
        if asset.branch == "feat/dirty" and asset.side is BranchSide.LOCAL
    )
    assert asset.dirty_worktree_paths == (str(path.resolve()),)
