from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.branch_lifecycle import (
    BranchAsset,
    BranchCleanupAction,
    BranchDisposition,
    BranchSide,
)
from delivery_control.domain.branch_refs import BranchInventory
from delivery_control.domain.errors import InvalidReceipt
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.services.branch_lifecycle_projection import (
    project_branch_lifecycle,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _record(
    branch: str,
    *,
    status: str,
    handed_back_sha: str | None = None,
    base_sha: str = SHA_A,
    owner_thread_id: str | None = None,
    superseded_pr_number: int | None = None,
    superseded_pr_head_sha: str | None = None,
    superseded_patch_fingerprint: str | None = None,
) -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id=f"LANE-{branch}",
        branch=branch,
        path=Path(f"/tmp/{branch.replace('/', '-')}"),
        status=status,
        scope=Scope.from_paths(modify=("ops/example.py",)),
        base_sha=base_sha,
        claim_generation=1,
        handed_back_sha=handed_back_sha,
        handback_valid=handed_back_sha is not None,
        owner_thread_id=owner_thread_id,
        superseded_pr_number=superseded_pr_number,
        superseded_pr_head_sha=superseded_pr_head_sha,
        superseded_patch_fingerprint=superseded_patch_fingerprint,
    )


def _pr(
    number: int,
    branch: str,
    *,
    state: str,
    head_sha: str,
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://github.com/example/repo/pull/{number}",
        branch=branch,
        base_sha=SHA_A,
        head_sha=head_sha,
        state=state,
        draft=False,
        mergeable=True,
    )


def test_every_local_and_remote_ref_is_partitioned_once() -> None:
    inventory = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("main", SHA_A), ("feat/orphan", SHA_B)),
            remote=(("main", SHA_A), ("feat/orphan", SHA_B), ("feat/remote", SHA_C)),
        )
    )

    assert len(inventory.assets) == 5
    assert len({(asset.side, asset.branch) for asset in inventory.assets}) == 5
    assert inventory.counts[BranchDisposition.PROTECTED.value] == 2
    assert inventory.counts[BranchDisposition.ORPHAN_LOCAL_RECONCILE.value] == 1
    assert inventory.counts[BranchDisposition.ORPHAN_REMOTE_RECONCILE.value] == 2


def test_open_pr_branch_is_durable_but_sha_drift_is_preserved() -> None:
    durable = project_branch_lifecycle(
        branch_inventory=BranchInventory(remote=(("feat/pr", SHA_B),)),
        pull_requests=(_pr(10, "feat/pr", state="OPEN", head_sha=SHA_B),),
    ).remote[0]
    drifted = project_branch_lifecycle(
        branch_inventory=BranchInventory(remote=(("feat/pr", SHA_C),)),
        pull_requests=(_pr(10, "feat/pr", state="OPEN", head_sha=SHA_B),),
    ).remote[0]

    assert durable.disposition is BranchDisposition.OPEN_PR_DURABLE
    assert durable.cleanup_action is BranchCleanupAction.PRESERVE_DURABLE_PR
    assert drifted.disposition is BranchDisposition.REMOTE_DRIFT
    assert drifted.cleanup_action is BranchCleanupAction.PRESERVE_REMOTE_DRIFT


def test_same_branch_refs_expose_exact_pair_for_equal_and_drifted_sha() -> None:
    equal = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("feat/pair", SHA_B),),
            remote=(("feat/pair", SHA_B),),
        )
    )
    drifted = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("feat/pair-drift", SHA_B),),
            remote=(("feat/pair-drift", SHA_C),),
        )
    )

    local_equal, remote_equal = equal.assets
    local_drift, remote_drift = drifted.assets
    assert (local_equal.paired_ref_side, local_equal.paired_ref_sha) == (
        BranchSide.REMOTE,
        SHA_B,
    )
    assert (remote_equal.paired_ref_side, remote_equal.paired_ref_sha) == (
        BranchSide.LOCAL,
        SHA_B,
    )
    assert (local_drift.paired_ref_side, local_drift.paired_ref_sha) == (
        BranchSide.REMOTE,
        SHA_C,
    )
    assert (remote_drift.paired_ref_side, remote_drift.paired_ref_sha) == (
        BranchSide.LOCAL,
        SHA_B,
    )
    assert local_drift.disposition is BranchDisposition.ORPHAN_LOCAL_RECONCILE
    assert remote_drift.disposition is BranchDisposition.ORPHAN_REMOTE_RECONCILE


def test_single_sided_ref_has_explicit_null_pair() -> None:
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/single", SHA_A),))
    ).local[0]

    assert asset.paired_ref_side is None
    assert asset.paired_ref_sha is None


def test_protected_main_keeps_exact_pair_evidence() -> None:
    assets = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("main", SHA_A),),
            remote=(("main", SHA_A),),
        )
    ).assets

    assert all(asset.disposition is BranchDisposition.PROTECTED for asset in assets)
    assert all(asset.paired_ref_sha == SHA_A for asset in assets)


def test_abandoned_handback_cannot_be_silently_deleted() -> None:
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/abandoned", SHA_B),)),
        records=(
            _record(
                "feat/abandoned",
                status="abandoned",
                handed_back_sha=SHA_B,
            ),
        ),
    ).local[0]

    assert asset.disposition is BranchDisposition.ABANDONED_WITH_HANDBACK
    assert (
        asset.cleanup_action
        is BranchCleanupAction.RECOVER_OWNER_OR_REQUIRE_DISCARD_PROOF
    )


def test_superseded_handback_is_a_distinct_terminal_candidate() -> None:
    branch = "feat/superseded"
    assets = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=((branch, SHA_B),),
            remote=((branch, SHA_C),),
        ),
        records=(
            _record(
                branch,
                status="abandoned",
                handed_back_sha=SHA_B,
                superseded_pr_number=42,
                superseded_pr_head_sha=SHA_C,
                superseded_patch_fingerprint="d" * 64,
            ),
        ),
        pull_requests=(_pr(42, branch, state="MERGED", head_sha=SHA_C),),
    ).assets

    assert {asset.disposition for asset in assets} == {
        BranchDisposition.SUPERSEDED_BY_MERGED_PR
    }
    assert all(
        asset.cleanup_action is BranchCleanupAction.CLEANUP_SUPERSEDED
        for asset in assets
    )


def test_branch_asset_retains_owner_thread_evidence() -> None:
    owner_thread_id = "01a016d3-1eb3-7722-8b30-3c54fe4c37ba"
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/owned", SHA_B),)),
        records=(
            _record(
                "feat/owned",
                status="active",
                handed_back_sha=SHA_B,
                owner_thread_id=owner_thread_id,
            ),
        ),
    ).local[0]

    assert asset.owner_thread_ids == (owner_thread_id,)


def test_merged_branch_requires_exact_terminal_proof_before_cleanup() -> None:
    ready = project_branch_lifecycle(
        branch_inventory=BranchInventory(remote=(("feat/merged", SHA_B),)),
        records=(_record("feat/merged", status="merged", handed_back_sha=SHA_B),),
        pull_requests=(_pr(11, "feat/merged", state="MERGED", head_sha=SHA_B),),
    ).remote[0]
    closed = project_branch_lifecycle(
        branch_inventory=BranchInventory(remote=(("feat/closed", SHA_B),)),
        pull_requests=(_pr(12, "feat/closed", state="CLOSED", head_sha=SHA_B),),
    ).remote[0]

    assert ready.disposition is BranchDisposition.MERGED_CLEANUP_READY
    assert ready.cleanup_ready
    assert closed.disposition is BranchDisposition.CLOSED_DISPOSITION_REQUIRED


def test_mismatched_merged_heads_are_unknown_not_cleanup_ready() -> None:
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(remote=(("feat/mismatch", SHA_B),)),
        records=(_record("feat/mismatch", status="merged", handed_back_sha=SHA_C),),
        pull_requests=(_pr(14, "feat/mismatch", state="MERGED", head_sha=SHA_B),),
    ).remote[0]

    assert asset.disposition is BranchDisposition.UNKNOWN
    assert asset.cleanup_action is BranchCleanupAction.INSPECT_UNKNOWN
    assert not asset.cleanup_ready


def test_active_registry_and_open_pr_must_share_one_head() -> None:
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/live-mismatch", SHA_B),)),
        records=(
            _record("feat/live-mismatch", status="active", handed_back_sha=SHA_B),
        ),
        pull_requests=(_pr(15, "feat/live-mismatch", state="OPEN", head_sha=SHA_C),),
    ).local[0]

    assert asset.disposition is BranchDisposition.UNKNOWN
    assert asset.cleanup_action is BranchCleanupAction.INSPECT_UNKNOWN


def test_multiple_open_prs_are_not_a_durable_single_branch_lane() -> None:
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(remote=(("feat/multiple-open", SHA_B),)),
        pull_requests=(
            _pr(16, "feat/multiple-open", state="OPEN", head_sha=SHA_B),
            _pr(17, "feat/multiple-open", state="OPEN", head_sha=SHA_B),
        ),
    ).remote[0]

    assert asset.disposition is BranchDisposition.UNKNOWN
    assert asset.cleanup_action is BranchCleanupAction.INSPECT_UNKNOWN


def test_dirty_physical_asset_is_retained_even_after_merge_evidence() -> None:
    path = Path("/tmp/dirty-worktree")
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/merged", SHA_B),)),
        records=(_record("feat/merged", status="merged", handed_back_sha=SHA_B),),
        pull_requests=(_pr(13, "feat/merged", state="MERGED", head_sha=SHA_B),),
        physical=(PhysicalWorktree(path=path, head_sha=SHA_B, branch="feat/merged"),),
        snapshots={
            path.resolve(): WorktreeSnapshot(
                path=path,
                branch="feat/merged",
                base_sha=SHA_A,
                head_sha=SHA_B,
                parent_sha=SHA_A,
                clean=False,
                changes=(),
            )
        },
    ).local[0]

    assert asset.disposition is BranchDisposition.ORPHAN_LOCAL_RECONCILE
    assert str(path.resolve()) in asset.dirty_worktree_paths


def test_duplicate_live_claims_are_unknown_and_not_cleanup_ready() -> None:
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/duplicate", SHA_B),)),
        records=(
            _record("feat/duplicate", status="active", handed_back_sha=SHA_B),
            _record("feat/duplicate", status="published", handed_back_sha=SHA_B),
        ),
    ).local[0]

    assert asset.disposition is BranchDisposition.UNKNOWN
    assert asset.cleanup_action is BranchCleanupAction.INSPECT_UNKNOWN


def test_explicit_backup_can_be_protected_without_being_main() -> None:
    asset = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            remote=(("backup/pre-github-cutover-20260819", SHA_B),)
        ),
        protected_branches=frozenset(
            {"main", "prod", "backup/pre-github-cutover-20260819"}
        ),
    ).remote[0]

    assert asset.disposition is BranchDisposition.PROTECTED
    assert asset.cleanup_action is BranchCleanupAction.PRESERVE_PROTECTED


def test_branch_asset_rejects_mismatched_protected_flag() -> None:
    with pytest.raises(InvalidReceipt):
        BranchAsset(
            branch="main",
            side=BranchSide.LOCAL,
            sha=SHA_A,
            disposition=BranchDisposition.PROTECTED,
            cleanup_action=BranchCleanupAction.PRESERVE_PROTECTED,
            reason="protected",
            protected=False,
        )
