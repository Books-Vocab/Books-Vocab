from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_parsing import (
    parse_demand_issue,
    parse_demand_issue_inventory,
)
from delivery_control.cli import _parser, run_command
from delivery_control.controller.capacity import (
    ControlAction,
    decide_capacity,
)
from delivery_control.controller.metrics import MergeCadence, measure_pipeline
from delivery_control.domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateSeverity,
    CandidateSpec,
)
from delivery_control.domain.demand_issues import (
    DemandIssueInventory,
    IssueDisposition,
    issue_body_sha256,
)
from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    InventoryProblem,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryCollisionClaim,
    RegistryCollisionInventory,
    RegistrySnapshot,
)
from delivery_control.services.candidate_contract import render_candidate_body
from delivery_control.services.demand_projection import project_demand_inventory
from delivery_control.services.issue_admission import assert_candidate_scope_available
from delivery_control.services.issue_triage import build_triage_plan

NOW = "2026-08-22T01:00:00Z"


def _payload(
    number: int,
    *,
    labels: tuple[str, ...] = (),
    body: str = "plain request",
) -> dict[str, object]:
    return {
        "id": f"I_{number}",
        "number": number,
        "url": f"https://github.com/owner/repo/issues/{number}",
        "title": f"Issue {number}",
        "body": body,
        "updatedAt": NOW,
        "labels": [{"name": label} for label in labels],
    }


def _spec(number: int, *, holds: tuple[str, ...] = ()) -> CandidateSpec:
    return CandidateSpec(
        severity=CandidateSeverity.P2,
        priority=number,
        scope=Scope.from_paths(modify=(f"ops/issue_{number}.py",)),
        acceptance=(f"Issue {number} is fixed.",),
        initial_holds=holds,
    )


def _record(
    number: int, status: str, *, external_id: str | None = None
) -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id=f"lane-{number}",
        branch=f"debug/issue-{number}",
        path=Path(f"/tmp/issue-{number}"),
        status=status,
        scope=Scope.from_paths(modify=(f"ops/issue_{number}.py",)),
        base_sha="a" * 40,
        claim_generation=1,
        external_ids=(() if external_id is None else (external_id,)),
    )


def _pr(number: int, state: str = "OPEN") -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://github.com/owner/repo/pull/{number}",
        branch=f"debug/issue-{number}",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state=state,
        draft=False,
        mergeable=True,
        title=f"fix Issue #{number}",
        body=f"Issue #{number}",
        node_id=f"PR_{number}",
    )


def test_raw_issue_inventory_keeps_malformed_entries_and_raw_total() -> None:
    payload = [_payload(1), {"number": 2}, _payload(3)]

    inventory = parse_demand_issue_inventory(payload)

    assert inventory.raw_open_issues == 3
    assert [item.number for item in inventory.records] == [1, 3]
    assert inventory.problems[0].identity == "Issue#2"
    assert inventory.source_entries[0].identity == "Issue#2"
    assert inventory.source_entries[0].issue_number == 2
    assert inventory.source_entries[0].disposition is IssueDisposition.SOURCE_PROBLEM
    assert inventory.unadmitted_open_issues == 3
    assert inventory.backlog_drained is False


def test_raw_issue_inventory_keeps_anonymous_malformed_entry_addressable() -> None:
    inventory = parse_demand_issue_inventory([_payload(1), None])

    assert inventory.raw_open_issues == 2
    assert inventory.source_entries[0].identity == "entry[1]"
    assert inventory.source_entries[0].issue_number is None
    assert inventory.disposition_counts[IssueDisposition.SOURCE_PROBLEM.value] == 1
    assert inventory.unadmitted_open_issues == 2


def test_metrics_count_each_malformed_source_entry_once() -> None:
    from delivery_control.domain.inventory import DeliveryInventory

    projected = project_demand_inventory(
        parse_demand_issue_inventory([_payload(1), None])
    )

    metrics = measure_pipeline(
        DeliveryInventory(
            lanes=(),
            demand_issues=projected,
            candidate_issues=projected.candidate_issues,
            dispatchable_candidate_issues=projected.dispatchable_candidate_issues,
        ),
        now=datetime(2026, 8, 22, tzinfo=UTC),
    )

    assert metrics.issue_source_problems == 1
    assert metrics.source_problems == 1


def test_incomplete_issue_inventory_keeps_unknown_backlog_distinct_from_zero() -> None:
    from delivery_control.domain.inventory import DeliveryInventory

    inventory = DemandIssueInventory(
        records=(),
        raw_count=None,
        complete=False,
        problems=(InventoryProblem("github", "open-issues", "rate limited"),),
    )
    metrics = measure_pipeline(
        DeliveryInventory(lanes=(), demand_issues=inventory),
        now=datetime(2026, 8, 22, tzinfo=UTC),
    )
    decision = decide_capacity(
        metrics,
        MergeCadence(3600, 0, 0.0, None, None, None),
    )

    assert metrics.raw_open_issues is None
    assert metrics.unadmitted_open_issues is None
    assert metrics.issue_inventory_complete is False
    assert metrics.backlog_drained is False
    assert ControlAction.TRIAGE_EXISTING_ISSUES in decision.actions


def test_unknown_raw_count_cannot_claim_complete_inventory() -> None:
    with pytest.raises(ValueError, match="unknown raw_count"):
        DemandIssueInventory(records=(), raw_count=None, complete=True)


def test_complete_issue_inventory_cannot_hide_unrepresented_raw_entries() -> None:
    with pytest.raises(ValueError, match="must represent every raw entry"):
        DemandIssueInventory(records=(), raw_count=1, complete=True)


def test_projection_assigns_one_disposition_with_fixed_precedence() -> None:
    candidate_body = render_candidate_body(_spec(5))
    raw = parse_demand_issue_inventory(
        [
            _payload(1, labels=("needs-triage",)),
            _payload(2, labels=("legacy-ticket",)),
            _payload(3, labels=("blocked",)),
            _payload(4, labels=("security",)),
            _payload(5, labels=(CANDIDATE_ISSUE_LABEL,), body=candidate_body),
            _payload(6, labels=(CANDIDATE_ISSUE_LABEL,), body="broken"),
            _payload(7, labels=("duplicate",)),
            _payload(8),
            _payload(9),
            _payload(10),
            _payload(11),
        ]
    )

    projected = project_demand_inventory(
        raw,
        registry_records=(
            _record(8, "active", external_id="#8"),
            _record(9, "published", external_id="#9"),
            _record(10, "merged", external_id="#10"),
        ),
        pull_requests=(_pr(11),),
    )

    by_number = {item.number: item.disposition for item in projected.records}
    assert by_number == {
        1: IssueDisposition.TRIAGE_REQUIRED,
        2: IssueDisposition.LEGACY_UNMAPPED,
        3: IssueDisposition.BLOCKED,
        4: IssueDisposition.SECURITY_HOLD,
        5: IssueDisposition.DISPATCHABLE_CANDIDATE,
        6: IssueDisposition.SOURCE_PROBLEM,
        7: IssueDisposition.TERMINAL_HISTORY,
        8: IssueDisposition.OWNER_BOUND,
        9: IssueDisposition.PUBLISHED_PR,
        10: IssueDisposition.TERMINAL_HISTORY,
        11: IssueDisposition.OWNER_BOUND,
    }
    assert projected.disposition_counts[IssueDisposition.TRIAGE_REQUIRED.value] == 1
    assert (
        projected.disposition_counts[IssueDisposition.DISPATCHABLE_CANDIDATE.value] == 1
    )
    assert projected.raw_open_issues == 11
    assert projected.unadmitted_open_issues == 3


def test_security_candidate_is_observable_but_not_dispatchable() -> None:
    issue = parse_demand_issue(
        _payload(
            20,
            labels=(CANDIDATE_ISSUE_LABEL,),
            body=render_candidate_body(_spec(20, holds=("security",))),
        )
    )
    projected = project_demand_inventory(DemandIssueInventory((issue,), raw_count=1))

    assert projected.records[0].disposition is IssueDisposition.SECURITY_HOLD
    assert projected.dispatchable_candidate_issues == ()
    assert projected.candidate_issues[0].number == 20


def test_explicit_security_hold_wins_over_existing_owner_mapping() -> None:
    issue = parse_demand_issue(_payload(21, body="## Security hold / priority\nP1"))

    projected = project_demand_inventory(
        DemandIssueInventory((issue,), raw_count=1),
        registry_records=(_record(21, "active", external_id="#21"),),
    )

    assert projected.records[0].disposition is IssueDisposition.SECURITY_HOLD


def test_triage_plan_is_stable_and_actionable() -> None:
    raw = parse_demand_issue_inventory(
        [_payload(2, labels=("legacy-ticket",)), _payload(1, labels=("security",))]
    )
    projected = project_demand_inventory(raw)

    plan = build_triage_plan(projected)

    assert [item.number for item in plan] == [1, 2]
    assert plan[0].next_action == "preserve_hold_and_route_security_clearance"
    assert plan[1].next_action == "reconcile_legacy_history_without_takeover"
    assert plan[0].body_sha256 == issue_body_sha256("plain request")


def test_metrics_expose_raw_backlog_without_starving_verified_candidates() -> None:
    raw = parse_demand_issue_inventory(
        [
            _payload(1),
            _payload(
                2,
                labels=(CANDIDATE_ISSUE_LABEL,),
                body=render_candidate_body(_spec(2)),
            ),
        ]
    )
    inventory = project_demand_inventory(raw)
    from delivery_control.domain.inventory import DeliveryInventory

    metrics = measure_pipeline(
        DeliveryInventory(
            lanes=(),
            demand_issues=inventory,
            candidate_issues=inventory.candidate_issues,
            dispatchable_candidate_issues=inventory.dispatchable_candidate_issues,
        ),
        now=datetime(2026, 8, 22, tzinfo=UTC),
    )
    cadence = MergeCadence(3600, 0, 0.0, None, None, None)
    decision = decide_capacity(metrics, cadence)

    assert metrics.raw_open_issues == 2
    assert metrics.candidate_issues == 1
    assert metrics.dispatchable_candidate_issues == 1
    assert metrics.recoverable_quarantine == 0
    assert metrics.unadmitted_open_issues == 1
    assert metrics.backlog_drained is False
    assert metrics.pipeline_ready is True
    assert metrics.ramp_ready is False
    assert ControlAction.TRIAGE_EXISTING_ISSUES in decision.actions
    assert ControlAction.REPLENISH_CANDIDATES not in decision.actions
    assert decision.desired_new_solvers == 1


def test_replenishment_waits_until_raw_backlog_is_drained() -> None:
    spec = _spec(30)
    issue = parse_demand_issue(
        _payload(30, labels=(CANDIDATE_ISSUE_LABEL,), body=render_candidate_body(spec))
    )
    inventory = project_demand_inventory(DemandIssueInventory((issue,), raw_count=1))
    from delivery_control.domain.inventory import DeliveryInventory

    metrics = measure_pipeline(
        DeliveryInventory(
            lanes=(),
            demand_issues=inventory,
            candidate_issues=inventory.candidate_issues,
            dispatchable_candidate_issues=inventory.dispatchable_candidate_issues,
        ),
        now=datetime(2026, 8, 22, tzinfo=UTC),
    )
    decision = decide_capacity(
        metrics,
        MergeCadence(3600, 0, 0.0, None, None, None),
    )

    assert metrics.backlog_drained is True
    assert ControlAction.REPLENISH_CANDIDATES in decision.actions


def test_candidate_admission_rejects_registry_scope_collision() -> None:
    with pytest.raises(PolicyViolation, match="active registry lane"):
        assert_candidate_scope_available(
            scope=_spec(41).scope,
            demand_issues=(),
            registry=RegistryCollisionInventory(
                records=(
                    RegistryCollisionClaim(
                        lane_id="lane-occupied",
                        branch="debug/occupied",
                        scope=_spec(41).scope,
                    ),
                )
            ),
            pull_requests=PullRequestInventory(records=()),
            changed_paths=lambda _number: (),
        )


def test_candidate_admission_rejects_open_pr_scope_collision() -> None:
    with pytest.raises(PolicyViolation, match="open PR #42"):
        assert_candidate_scope_available(
            scope=_spec(42).scope,
            demand_issues=(),
            registry=RegistryCollisionInventory(records=()),
            pull_requests=PullRequestInventory(records=(_pr(42),)),
            changed_paths=lambda _number: ("ops/issue_42.py",),
        )


def test_cli_issue_inventory_and_triage_plan_wrap_versioned_schemas() -> None:
    raw = parse_demand_issue_inventory([_payload(1)])
    projected = project_demand_inventory(raw)

    class StubApplication:
        def issue_inventory(self) -> DemandIssueInventory:
            return projected

        def triage_plan(self) -> tuple[object, ...]:
            return build_triage_plan(projected)

    application = StubApplication()
    inventory_args = _parser().parse_args(["issue-inventory"])
    triage_args = _parser().parse_args(["triage-plan"])

    inventory_result = run_command(inventory_args, application)  # type: ignore[arg-type]
    triage_result = run_command(triage_args, application)  # type: ignore[arg-type]

    assert inventory_result["schema"] == "kg.delivery.issue-inventory.v1"
    assert inventory_result["raw_total"] == 1
    assert (
        inventory_result["partition_totals"][IssueDisposition.TRIAGE_REQUIRED.value]
        == 1
    )
    assert triage_result["schema"] == "kg.delivery.triage-plan.v1"
