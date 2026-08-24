from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.branch_lifecycle import (
    BranchCleanupAction,
    BranchDisposition,
    BranchRegistryEvidence,
    BranchSide,
)
from delivery_control.domain.branch_refs import BranchInventory
from delivery_control.domain.inventory import (
    DeliveryInventory,
    LaneInspection,
)
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.domain.states import (
    LaneDecision,
    LaneState,
    NextAction,
)
from delivery_control.domain.unreachable_commits import (
    UnreachableCommitInventory,
)
from delivery_control.services.branch_audit import (
    BranchAuditSourceProblem,
    build_branch_audit,
)
from delivery_control.services.branch_lifecycle_projection import (
    project_branch_lifecycle,
)
from delivery_control.services.orphan_branch import (
    OrphanBranchPreflight,
)

SHA_A = "a" * 40
SHA_B = "b" * 40


def _record(
    branch: str,
    status: str,
    head: str | None = None,
    owner_thread_id: str | None = None,
) -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id=f"LANE-{branch}",
        branch=branch,
        path=Path(f"/tmp/{branch.replace('/', '-')}"),
        status=status,
        scope=Scope.from_paths(modify=("ops/example.py",)),
        base_sha=SHA_A,
        claim_generation=1,
        handed_back_sha=head,
        handback_valid=head is not None,
        owner_thread_id=owner_thread_id,
    )


def _pr(number: int, branch: str, state: str, head: str) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://example.test/pull/{number}",
        branch=branch,
        base_sha=SHA_A,
        head_sha=head,
        state=state,
        draft=False,
        mergeable=True,
    )


def test_branch_audit_emits_one_action_per_ref_and_safe_cleanup_candidate() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("main", SHA_A), ("feat/orphan", SHA_A)),
            remote=(("main", SHA_A), ("feat/merged", SHA_B)),
        ),
        records=(_record("feat/merged", "merged", SHA_B),),
        pull_requests=(_pr(1483, "feat/merged", "MERGED", SHA_B),),
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        physical_worktrees=(PhysicalWorktree(Path("/tmp/main"), SHA_A, "main"),),
        live_main_sha=SHA_A,
        local_main_sha=SHA_A,
    )

    report = build_branch_audit(
        inventory,
        orphan_preflights={
            "feat/orphan": OrphanBranchPreflight(
                schema="kg.delivery.orphan-branch-preflight.v1",
                branch="feat/orphan",
                expected_head_sha=SHA_A,
                main_sha=SHA_A,
                eligible=True,
                passed_checks=("all exact checks passed",),
                blockers=(),
            )
        },
    )

    assert report.schema == "kg.delivery.branch-audit.v1"
    assert report.complete
    assert report.verdict == "complete"
    assert report.source_problem_actions == ()
    assert report.raw_local_branches == 2
    assert report.raw_remote_branches == 2
    assert report.physical_worktrees == 1
    assert len(report.actions) == len(report.assets) == 4
    assert len(report.safe_terminal_actions) == 2
    cleanup = next(
        item
        for item in report.safe_terminal_actions
        if item.cleanup_action is BranchCleanupAction.CLEANUP_MERGED
    )
    assert cleanup.cleanup_action is BranchCleanupAction.CLEANUP_MERGED
    assert cleanup.suggested_command == "./ops/delivery.py cleanup-merged --pr 1483"
    assert any(
        item.disposition is BranchDisposition.ORPHAN_LOCAL_RECONCILE
        and item.side is BranchSide.LOCAL
        and item.safe_terminal
        for item in report.actions
    )


def test_branch_audit_exposes_owner_evidence_for_owner_lane() -> None:
    owner_thread_id = "01a016d3-1eb3-7722-8b30-3c54fe4c37ba"
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/owned", SHA_A),)),
        records=(
            _record(
                "feat/owned",
                "active",
                SHA_A,
                owner_thread_id=owner_thread_id,
            ),
        ),
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        live_main_sha=SHA_A,
        local_main_sha=SHA_A,
    )

    report = build_branch_audit(inventory)

    action = report.actions[0]
    assert action.category == "owner_lane"
    assert action.owner_thread_ids == (owner_thread_id,)
    assert report.assets[0].owner_thread_ids == (owner_thread_id,)


def test_branch_audit_action_preserves_exact_pair_without_changing_disposition() -> (
    None
):
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("feat/audit-pair", SHA_A),),
            remote=(("feat/audit-pair", SHA_B),),
        )
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        live_main_sha=SHA_A,
        local_main_sha=SHA_A,
    )

    report = build_branch_audit(inventory)

    local_action = next(
        item for item in report.actions if item.side is BranchSide.LOCAL
    )
    remote_action = next(
        item for item in report.actions if item.side is BranchSide.REMOTE
    )
    assert (local_action.paired_ref_side, local_action.paired_ref_sha) == (
        BranchSide.REMOTE,
        SHA_B,
    )
    assert (remote_action.paired_ref_side, remote_action.paired_ref_sha) == (
        BranchSide.LOCAL,
        SHA_A,
    )
    assert local_action.disposition is BranchDisposition.ORPHAN_LOCAL_RECONCILE
    assert remote_action.disposition is BranchDisposition.ORPHAN_REMOTE_RECONCILE


def test_branch_asset_exposes_complete_registry_evidence() -> None:
    record = RegistrySnapshot(
        lane_id="LANE-EVIDENCE",
        branch="feat/evidence",
        path=Path("/tmp/feat-evidence"),
        status="active",
        scope=Scope.from_paths(modify=("ops/z.py", "ops/a.py")),
        base_sha=SHA_A,
        published_base_sha=SHA_B,
        external_ids=("z-external", "a-external"),
        claim_generation=2,
        owner_thread_id="owner-evidence",
        handed_back_sha=SHA_A,
        handback_digest="d" * 64,
    )

    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/evidence", SHA_A),)),
        records=(record,),
    )

    assert lifecycle.assets[0].registry_evidence == (
        BranchRegistryEvidence(
            lane_id="LANE-EVIDENCE",
            branch="feat/evidence",
            path=str(Path("/tmp/feat-evidence").resolve()),
            status="active",
            claim_generation=2,
            base_sha=SHA_A,
            published_base_sha=SHA_B,
            handed_back_sha=SHA_A,
            handback_digest="d" * 64,
            owner_thread_id="owner-evidence",
            scope_paths=("ops/a.py", "ops/z.py"),
            external_ids=("a-external", "z-external"),
        ),
    )


def test_branch_asset_registry_evidence_preserves_deterministic_multi_record_order() -> (
    None
):
    records = (
        RegistrySnapshot(
            lane_id="LANE-Z",
            branch="feat/multi-evidence",
            path=Path("/tmp/multi-z"),
            status="abandoned",
            scope=Scope.from_paths(modify=("ops/z.py",)),
            base_sha=SHA_A,
            claim_generation=3,
            handed_back_sha=SHA_B,
        ),
        RegistrySnapshot(
            lane_id="LANE-A",
            branch="feat/multi-evidence",
            path=Path("/tmp/multi-a"),
            status="merged",
            scope=Scope.from_paths(modify=("ops/a.py",)),
            base_sha=SHA_A,
            claim_generation=1,
            handed_back_sha=SHA_B,
        ),
    )

    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            remote=(("feat/multi-evidence", SHA_B),),
        ),
        records=records,
    )

    assert tuple(item.lane_id for item in lifecycle.assets[0].registry_evidence) == (
        "LANE-A",
        "LANE-Z",
    )
    assert tuple(item.status for item in lifecycle.assets[0].registry_evidence) == (
        "merged",
        "abandoned",
    )


def test_branch_asset_without_registry_has_empty_evidence() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/unregistered", SHA_A),))
    )

    assert lifecycle.assets[0].registry_evidence == ()


def test_branch_audit_keeps_unknown_asset_incomplete() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/mismatch", SHA_B),)),
        records=(_record("feat/mismatch", "merged", SHA_A),),
        pull_requests=(_pr(1499, "feat/mismatch", "MERGED", SHA_B),),
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        live_main_sha=SHA_A,
        local_main_sha=SHA_A,
    )

    report = build_branch_audit(inventory)

    assert report.assets[0].disposition is BranchDisposition.UNKNOWN
    assert report.actions[0].category == "inspect"
    assert report.actions[0].safe_terminal is False
    assert report.complete is False
    assert report.verdict == "incomplete"
    assert report.safe_terminal_actions == ()


def test_blocked_local_orphan_emits_read_only_content_review_command() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/unlanded", SHA_B),))
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        live_main_sha=SHA_A,
        local_main_sha=SHA_A,
    )

    report = build_branch_audit(
        inventory,
        orphan_preflights={
            "feat/unlanded": OrphanBranchPreflight(
                schema="kg.delivery.orphan-branch-preflight.v1",
                branch="feat/unlanded",
                expected_head_sha=SHA_B,
                main_sha=SHA_A,
                eligible=False,
                passed_checks=(),
                blockers=("orphan branch tip is not an ancestor of live origin/main",),
            )
        },
    )

    action = report.actions[0]
    assert action.safe_terminal is False
    assert action.review_command == (
        "./ops/delivery.py branch-inspect --branch feat/unlanded "
        "--expected-head-sha " + SHA_B
    )


def test_branch_audit_keeps_source_problems_visible_and_fail_closed() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/orphan", SHA_B),))
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        source_problems=(InventoryProblem("registry", "broken", "bad record"),),
    )

    report = build_branch_audit(inventory)

    assert report.complete is False
    assert report.verdict == "incomplete"
    assert len(report.source_problems) == 1
    assert report.safe_terminal_actions == ()
    assert report.source_problem_counts == {"registry": 1}
    assert report.source_problem_actions == (
        BranchAuditSourceProblem(
            source="registry",
            identity="broken",
            reason="bad record",
            category="registry_source_problem",
            next_step=(
                "preserve all branch/worktree assets; the malformed registry identity "
                "cannot be scoped safely, so reconcile it through its supported "
                "owner lifecycle before cleanup"
            ),
        ),
    )
    assert report.raw_active_registry_records == 0
    assert report.malformed_registry_records == 0
    assert report.registry_record_problem_actions == ()
    assert report.registry_record_problem_status_counts == {}


def test_branch_audit_counts_malformed_active_registry_record_without_admitting_it() -> (
    None
):
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/malformed", SHA_A),))
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/malformed",
                "registry base must be an exact commit SHA",
                identity_kind="branch",
                record_status="active",
            ),
        ),
    )

    report = build_branch_audit(inventory)

    assert report.complete is False
    assert report.active_registry_records == 0
    assert report.raw_active_registry_records == 1
    assert report.malformed_registry_records == 1
    assert report.registry_record_problem_actions == (
        BranchAuditSourceProblem(
            source="registry",
            identity="feat/malformed",
            reason="registry base must be an exact commit SHA",
            category="registry_source_problem",
            next_step=(
                "preserve feat/malformed assets; reconcile its malformed registry "
                "record through the supported owner lifecycle before cleanup"
            ),
            identity_kind="branch",
            scope="branch",
            affected_branch="feat/malformed",
            record_status="active",
        ),
    )
    assert report.registry_record_problem_status_counts == {"active": 1}


def test_branch_audit_deduplicates_active_record_cardinality_but_keeps_diagnostics() -> (
    None
):
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(),
        ),
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/malformed",
                "claim_generation must be a non-negative integer",
                identity_kind="branch",
                record_status="active",
            ),
            InventoryProblem(
                "registry",
                "feat/malformed",
                "lifecycle timestamp is malformed",
                identity_kind="branch",
                record_status="active",
            ),
        ),
    )

    report = build_branch_audit(inventory)

    assert report.raw_active_registry_records == 1
    assert report.malformed_registry_records == 2
    assert len(report.registry_record_problem_actions) == 2
    assert report.registry_record_problem_status_counts == {"active": 2}


def test_branch_audit_counts_distinct_active_identities_and_excludes_terminal_history() -> (
    None
):
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(),
        ),
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/malformed",
                "claim_generation invalid",
                identity_kind="branch",
                record_status="active",
            ),
            InventoryProblem(
                "registry",
                "feat/malformed",
                "timestamp invalid",
                identity_kind="branch",
                record_status="active",
            ),
            InventoryProblem(
                "registry",
                "/tmp/malformed",
                "path claim invalid",
                identity_kind="path",
                record_status="active",
            ),
            InventoryProblem(
                "registry",
                "feat/malformed",
                "old terminal diagnostic",
                identity_kind="branch",
                record_status="abandoned",
            ),
        ),
    )

    report = build_branch_audit(inventory)

    assert report.raw_active_registry_records == 2
    assert report.malformed_registry_records == 4
    assert report.registry_record_problem_status_counts == {
        "abandoned": 1,
        "active": 3,
    }


def test_branch_audit_marks_unobserved_registry_history_as_quarantined() -> None:
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(),
        ),
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/old-history",
                "registry base must be an exact commit SHA",
                identity_kind="branch",
                record_status="abandoned",
            ),
        ),
    )

    report = build_branch_audit(inventory)

    action = report.source_problem_actions[0]
    assert action.actionability == "quarantined_history"
    assert report.actionable_source_problems == 0
    assert report.quarantined_source_problems == 1
    assert "no matching local/remote branch" in action.next_step


def test_branch_audit_keeps_observed_registry_problem_blocking() -> None:
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(local=(("feat/live-history", SHA_A),)),
        ),
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/live-history",
                "registry base must be an exact commit SHA",
                identity_kind="branch",
                record_status="abandoned",
            ),
        ),
    )

    report = build_branch_audit(inventory)

    action = report.source_problem_actions[0]
    assert action.actionability == "blocking"
    assert report.actionable_source_problems == 1
    assert report.quarantined_source_problems == 0


def test_branch_audit_withholds_otherwise_safe_cleanup_when_source_is_incomplete() -> (
    None
):
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("feat/merged", SHA_B),),
        ),
        records=(_record("feat/merged", "merged", SHA_B),),
        pull_requests=(_pr(1483, "feat/merged", "MERGED", SHA_B),),
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        source_problems=(InventoryProblem("registry", "broken", "bad record"),),
    )

    report = build_branch_audit(inventory)

    assert report.actions[0].category == "source_incomplete"
    assert report.actions[0].safe_terminal is False
    assert report.actions[0].suggested_command is None
    assert report.safe_terminal_actions == ()


def test_branch_audit_scopes_registry_problem_to_exact_branch() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("feat/merged", SHA_B), ("feat/other", SHA_A)),
        ),
        records=(_record("feat/merged", "merged", SHA_B),),
        pull_requests=(_pr(1483, "feat/merged", "MERGED", SHA_B),),
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/other-history",
                "malformed legacy record",
                identity_kind="branch",
            ),
        ),
    )

    report = build_branch_audit(
        inventory,
        orphan_preflights={
            "feat/other": OrphanBranchPreflight(
                schema="kg.delivery.orphan-branch-preflight.v1",
                branch="feat/other",
                expected_head_sha=SHA_A,
                main_sha=SHA_A,
                eligible=True,
                passed_checks=("all exact checks passed",),
                blockers=(),
            )
        },
    )

    assert report.complete is False
    assert report.source_problem_scope_counts == {"branch": 1}
    assert len(report.safe_terminal_actions) == 2
    assert report.source_problem_actions[0].affected_branch == "feat/other-history"
    assert report.source_problem_actions[0].scope == "branch"


def test_branch_audit_surfaces_scoped_problem_on_blocked_orphan_action() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/other", SHA_B),))
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/other",
                "malformed legacy record",
                identity_kind="branch",
                record_status="abandoned",
            ),
        ),
    )

    report = build_branch_audit(inventory)

    action = report.actions[0]
    assert action.category == "source_incomplete"
    assert action.safe_terminal is False
    assert "source inventory problems affecting this branch" in action.next_step
    assert "registry:feat/other" in action.next_step
    assert action.review_command == (
        "./ops/delivery.py branch-inspect --branch feat/other "
        "--expected-head-sha " + SHA_B
    )


def test_branch_audit_withholds_exact_affected_branch_but_not_unrelated_branch() -> (
    None
):
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(
            local=(("feat/merged", SHA_B), ("feat/other", SHA_A)),
        ),
        records=(_record("feat/merged", "merged", SHA_B),),
        pull_requests=(_pr(1483, "feat/merged", "MERGED", SHA_B),),
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        source_problems=(
            InventoryProblem(
                "registry",
                "feat/merged",
                "malformed target record",
                identity_kind="branch",
            ),
        ),
    )

    report = build_branch_audit(
        inventory,
        orphan_preflights={
            "feat/other": OrphanBranchPreflight(
                schema="kg.delivery.orphan-branch-preflight.v1",
                branch="feat/other",
                expected_head_sha=SHA_A,
                main_sha=SHA_A,
                eligible=True,
                passed_checks=("all exact checks passed",),
                blockers=(),
            )
        },
    )

    affected = next(item for item in report.actions if item.branch == "feat/merged")
    unrelated = next(item for item in report.actions if item.branch == "feat/other")
    assert affected.safe_terminal is False
    assert affected.category == "source_incomplete"
    assert unrelated.safe_terminal is True
    assert len(report.safe_terminal_actions) == 1


def test_branch_audit_keeps_unscoped_source_problem_global() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/orphan", SHA_A),))
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
        source_problems=(
            InventoryProblem("registry", "/tmp/legacy-record", "malformed", "path"),
        ),
    )

    report = build_branch_audit(inventory)

    assert report.source_problem_scope_counts == {"global": 1}
    assert report.safe_terminal_actions == ()


def test_branch_audit_exposes_local_orphan_preflight_blockers() -> None:
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/orphan", SHA_B),))
    )
    inventory = DeliveryInventory(lanes=(), branch_lifecycle=lifecycle)
    preflight = OrphanBranchPreflight(
        schema="kg.delivery.orphan-branch-preflight.v1",
        branch="feat/orphan",
        expected_head_sha=SHA_B,
        main_sha=SHA_A,
        eligible=False,
        passed_checks=("canonical main is clean",),
        blockers=("remote branch still exists", "tip is not an ancestor"),
    )

    report = build_branch_audit(
        inventory,
        orphan_preflights={"feat/orphan": preflight},
    )
    action = report.actions[0]

    assert action.safe_terminal is False
    assert action.category == "local_orphan_blocked"
    assert "remote branch still exists" in action.next_step
    assert action.orphan_preflight == preflight


def test_branch_audit_surfaces_registry_only_active_claim() -> None:
    record = _record("debug/missing-registry-ref", "active", SHA_B)
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key=record.lane_id,
                registry=record,
                physical=None,
                snapshot=None,
                pull_requests=(),
                decision=LaneDecision(
                    LaneState.BLOCKED_OWNER,
                    NextAction.RECOVER_OWNER,
                    "registry claim has no observed worktree",
                ),
            ),
        ),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(),
        ),
    )

    report = build_branch_audit(inventory)

    assert report.complete is False
    assert report.verdict == "incomplete"
    assert report.actions == ()
    assert len(report.registry_only_actions) == 1
    action = report.registry_only_actions[0]
    assert action.branch == "debug/missing-registry-ref"
    assert action.status == "active"
    assert action.claim_generation == 1
    assert action.handed_back_sha == SHA_B
    assert action.registry_evidence.owner_thread_id is None
    assert action.registry_evidence.published_base_sha is None
    assert action.registry_evidence.handback_digest is None
    assert action.registry_evidence.scope_paths == ("ops/example.py",)
    assert action.registry_evidence.external_ids == ()
    assert action.safe_terminal is False
    assert action.category == "registry_only_residue"
    assert "recover the original owner" in action.next_step
    assert report.registry_only_status_counts == {"active": 1}


def test_branch_audit_surfaces_registry_only_published_claim() -> None:
    record = _record("feat/missing-published-ref", "published", SHA_B)
    inventory = DeliveryInventory(
        lanes=(
            LaneInspection(
                key=record.lane_id,
                registry=record,
                physical=None,
                snapshot=None,
                pull_requests=(),
                decision=LaneDecision(
                    LaneState.PUBLISHED_LOCAL_CLEANUP,
                    NextAction.CLEANUP_LOCAL,
                    "published claim has no observed ref",
                ),
            ),
        ),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(),
        ),
    )

    report = build_branch_audit(inventory)

    assert report.complete is False
    assert len(report.registry_only_actions) == 1
    action = report.registry_only_actions[0]
    assert action.status == "published"
    assert "reconcile the published claim" in action.next_step
    assert report.registry_only_status_counts == {"published": 1}


def test_branch_audit_quarantines_unreachable_commit_objects_without_lane_actions() -> (
    None
):
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(),
        ),
    )

    report = build_branch_audit(
        inventory,
        unreachable_commits=UnreachableCommitInventory(
            shas=(SHA_A, SHA_B),
        ),
    )

    assert report.complete is True
    assert report.unreachable_commit_count == 2
    assert report.unreachable_commit_sample == (SHA_A, SHA_B)
    assert "correlate unreachable commit objects" in report.unreachable_commit_next_step


def test_branch_audit_projects_unreachable_source_diagnostics_into_completeness() -> (
    None
):
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=project_branch_lifecycle(
            branch_inventory=BranchInventory(),
        ),
    )

    report = build_branch_audit(
        inventory,
        unreachable_commits=UnreachableCommitInventory(
            problems=("git fsck exited with 8",),
            complete=False,
        ),
    )

    assert report.complete is False
    assert report.verdict == "incomplete"
    assert report.source_problems == (
        InventoryProblem(
            "git",
            "unreachable-commits",
            "git fsck exited with 8",
            identity_kind="git_objects",
        ),
    )
    assert report.source_problem_scope_counts == {"git_objects": 1}
    assert report.source_problem_actions[0].category == "git_source_problem"


def test_branch_audit_keeps_exact_orphan_cleanup_independent_of_git_object_problems() -> (
    None
):
    lifecycle = project_branch_lifecycle(
        branch_inventory=BranchInventory(local=(("feat/orphan", SHA_A),))
    )
    inventory = DeliveryInventory(
        lanes=(),
        branch_lifecycle=lifecycle,
    )

    report = build_branch_audit(
        inventory,
        orphan_preflights={
            "feat/orphan": OrphanBranchPreflight(
                schema="kg.delivery.orphan-branch-preflight.v1",
                branch="feat/orphan",
                expected_head_sha=SHA_A,
                main_sha=SHA_A,
                eligible=True,
                passed_checks=("all exact checks passed",),
                blockers=(),
            )
        },
        unreachable_commits=UnreachableCommitInventory(
            problems=("git fsck exited with 8",),
            complete=False,
        ),
    )

    assert report.complete is False
    assert report.source_problem_scope_counts == {"git_objects": 1}
    assert report.source_problem_actions[0].scope == "git_objects"
    action = report.actions[0]
    assert action.safe_terminal is True
    assert action.suggested_command == (
        "./ops/delivery.py discard-orphan-branch "
        "--branch feat/orphan --expected-head-sha " + SHA_A
    )
