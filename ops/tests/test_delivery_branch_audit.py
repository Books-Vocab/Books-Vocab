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
from delivery_control.domain.branch_refs import BranchInventory  # noqa: E402
from delivery_control.domain.inventory import DeliveryInventory  # noqa: E402
from delivery_control.domain.models import Scope  # noqa: E402
from delivery_control.domain.observations import (  # noqa: E402
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.services.branch_audit import (  # noqa: E402
    BranchAuditSourceProblem,
    build_branch_audit,
)
from delivery_control.services.branch_lifecycle_projection import (  # noqa: E402
    project_branch_lifecycle,
)
from delivery_control.services.orphan_branch import (  # noqa: E402
    OrphanBranchPreflight,
)


SHA_A = "a" * 40
SHA_B = "b" * 40


def _record(branch: str, status: str, head: str | None = None) -> RegistrySnapshot:
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
