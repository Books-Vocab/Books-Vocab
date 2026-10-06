from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_parsing import parse_pull_request
from delivery_control.adapters.github_queries import GitHubQueries
from delivery_control.controller.capacity import ControlAction, decide_capacity
from delivery_control.controller.dogfood import assess_dogfood_readiness
from delivery_control.controller.metrics import (
    MergeCadence,
    PipelineMetrics,
    measure_pipeline,
)
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import PullRequestSnapshot, RegistrySnapshot
from delivery_control.domain.states import LaneDecision, LaneState, NextAction
from delivery_control.services.inspect import DeliveryInventory, LaneInspection


class StaticClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def load_json(self, argv: tuple[str, ...]) -> object:
        self.calls.append(argv)
        return self.responses.pop(0)


def _payload(
    number: int = 1, *, review_decision: object = "REVIEW_REQUIRED"
) -> dict[str, object]:
    return {
        "id": f"PR_{number}",
        "number": number,
        "url": f"https://example.test/pull/{number}",
        "headRefName": f"feat/{number}",
        "baseRefName": "main",
        "baseRefOid": "a" * 40,
        "headRefOid": "b" * 40,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "title": f"PR {number}",
        "body": "",
        "autoMergeRequest": None,
        "labels": [],
        "reviewDecision": review_decision,
    }


def _snapshot(number: int, review_decision: str | None) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://example.test/pull/{number}",
        branch=f"feat/{number}",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
        review_decision=review_decision,
    )


def _inventory(*pull_requests: PullRequestSnapshot) -> DeliveryInventory:
    record = RegistrySnapshot(
        lane_id="lane",
        branch=pull_requests[0].branch,
        path=Path("/tmp/lane"),
        status="published",
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha="a" * 40,
        claim_generation=1,
    )
    return DeliveryInventory(
        lanes=(
            LaneInspection(
                key="lane",
                registry=record,
                physical=None,
                snapshot=None,
                pull_requests=pull_requests,
                decision=LaneDecision(
                    LaneState.PR_WAITING_REQUIRED,
                    NextAction.WAIT_REQUIRED,
                    "waiting",
                ),
            ),
        )
    )


def test_parser_preserves_github_review_decision_and_unknown_is_fail_closed() -> None:
    assert (
        parse_pull_request(_payload(review_decision="APPROVED")).review_decision
        == "APPROVED"
    )
    assert (
        parse_pull_request(
            _payload(review_decision="CHANGES_REQUESTED")
        ).review_decision
        == "CHANGES_REQUESTED"
    )
    assert (
        parse_pull_request(_payload(review_decision="REVIEW_REQUIRED")).review_decision
        == "REVIEW_REQUIRED"
    )
    assert (
        parse_pull_request(_payload(review_decision="NOT_A_DECISION")).review_decision
        is None
    )
    assert parse_pull_request(_payload(review_decision=None)).review_decision is None
    missing = _payload()
    del missing["reviewDecision"]
    assert parse_pull_request(missing).review_decision is None


def test_open_and_branch_history_queries_request_review_decision() -> None:
    open_client = StaticClient([[_payload(review_decision="REVIEW_REQUIRED")]])
    open_inventory = GitHubQueries(
        client=open_client,
        repository_name=lambda: "owner/repo",
    ).list_open_pull_requests()
    assert open_inventory.records[0].review_decision == "REVIEW_REQUIRED"
    assert "reviewDecision" in open_client.calls[0][-1]

    history_payload = {
        "data": {
            "repository": {
                "branch0": {
                    "nodes": [
                        {
                            **_payload(review_decision="CHANGES_REQUESTED"),
                            "labels": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            },
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    }
    history_client = StaticClient([history_payload])
    history = GitHubQueries(
        client=history_client,
        repository_name=lambda: "owner/repo",
    ).list_pull_requests_for_branches(("feat/1",))
    assert history.records[0].review_decision == "CHANGES_REQUESTED"
    query = next(item for item in history_client.calls[0] if item.startswith("query="))
    assert "reviewDecision" in query


@pytest.mark.parametrize(
    ("review_decision", "field"),
    (
        ("REVIEW_REQUIRED", "review_required"),
        ("CHANGES_REQUESTED", "review_changes_requested"),
        ("APPROVED", "review_approved"),
        (None, "review_observation_unknown"),
    ),
)
def test_measured_metrics_count_review_observations_once(
    review_decision: str | None, field: str
) -> None:
    inventory = _inventory(
        _snapshot(1, review_decision),
        _snapshot(1, review_decision),
    )

    metrics = measure_pipeline(inventory)

    assert metrics.raw_open_prs == 1
    assert getattr(metrics, field) == 1
    assert metrics.review_gate_unresolved == (0 if field == "review_approved" else 1)


def test_conflicting_duplicate_review_observations_are_unknown() -> None:
    metrics = measure_pipeline(
        _inventory(_snapshot(1, "APPROVED"), _snapshot(1, "REVIEW_REQUIRED"))
    )

    assert metrics.raw_open_prs == 1
    assert metrics.review_approved == 0
    assert metrics.review_required == 0
    assert metrics.review_observation_unknown == 1
    assert metrics.review_gate_unresolved == 1


def test_legacy_metrics_keep_review_inventory_unknown() -> None:
    metrics = PipelineMetrics(
        active_development=0,
        handbacks_publishable=0,
        published_local_cleanup=0,
        cleanup_pending=0,
        open_prs=1,
        unmapped_open_prs=0,
        duplicate_pr_mappings=0,
        required_green=1,
        required_running=0,
        required_failed=0,
        required_absent=0,
        pr_contract_failed=0,
        merge_queue_depth=0,
        terminal_cleanup=0,
        blocked_lanes=0,
        physical_worktrees=0,
        source_problems=0,
        candidate_issues=0,
        reanchor_required=0,
    )

    assert metrics.review_required is None
    assert metrics.review_gate_unresolved is None
    decision = decide_capacity(
        metrics,
        MergeCadence(3600, 1, 1.0, 60.0, 60.0, 60.0),
    )
    assert ControlAction.AUDIT_PR_REVIEW_GATE not in decision.actions


def test_review_gate_is_audit_only_and_dogfood_reports_it_alongside_pr_reservoir() -> (
    None
):
    metrics = measure_pipeline(
        _inventory(_snapshot(1, "REVIEW_REQUIRED"), _snapshot(2, "APPROVED"))
    )
    cadence = MergeCadence(900, 3, 12.0, 60.0, 60.0, 60.0)

    decision = decide_capacity(metrics, cadence)
    assert ControlAction.AUDIT_PR_REVIEW_GATE in decision.actions
    assert ControlAction.DISPATCH_SOLVERS not in decision.actions

    readiness = assess_dogfood_readiness(
        local_main_sha="a" * 40,
        origin_main_sha="a" * 40,
        canonical_branch="main",
        canonical_clean=True,
        main_protected=True,
        required_status_contexts=("required",),
        merge_queue_enabled=True,
        physical_worktree_count=1,
        canonical_worktree_present=True,
        metrics=metrics,
        cadence=cadence,
    )
    assert "owner-mapped PR reservoir is not empty" in readiness.blockers
    assert any("review gate" in message for message in readiness.blockers)
