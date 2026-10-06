from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import HandbackOutcome, HandbackReceipt, Scope
from delivery_control.domain.observations import PullRequestSnapshot
from delivery_control.domain.states import HoldKind
from delivery_control.services.pr_contract import (
    parse_pull_request_body,
    pull_request_holds,
    render_pull_request_body,
    validate_pull_request_body,
)


def _receipt() -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="ISSUE-1",
        owner_thread_id="thread-1",
        claim_generation=3,
        branch="feat/delivery",
        worktree_path="/tmp/delivery",
        base_sha="a" * 40,
        parent_sha="a" * 40,
        head_sha="b" * 40,
        origin_main_sha="d" * 40,
        content_digest="e" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


def test_body_is_deterministic_and_satisfies_readiness_contract() -> None:
    body = render_pull_request_body(_receipt())

    assert body.startswith("## Scope\n")
    assert "## Handback\n" in body
    assert "## Validation\n" in body
    assert "## Impact\n" in body
    assert "kg.worktree.handback.v1" in body
    assert "kg.delivery.holds.v1" in body
    assert "Base SHA:" in body and "Head SHA:" in body
    assert body.count("Digest:") == 1
    assert "GitHub required checks are authoritative" in body
    assert parse_pull_request_body(body) == _receipt()


def test_body_canonically_round_trips_typed_handback_outcomes() -> None:
    receipt = replace(
        _receipt(),
        validation=(
            HandbackOutcome.from_payload(
                {"summary": "green", "status": "success", "name": "tests"}
            ),
        ),
    )

    body = render_pull_request_body(receipt)

    assert (
        '- Handback outcome 1: `{"name":"tests","status":"success",'
        '"summary":"green"}`'
    ) in body
    assert parse_pull_request_body(body) == receipt
    with pytest.raises(PolicyViolation, match="receipt is invalid"):
        parse_pull_request_body(
            body.replace('"status":"success"', '"status":"failure"')
        )


def test_body_preserves_initial_hold_impact_separately_from_active_holds() -> None:
    receipt = replace(_receipt(), initial_holds=("security",))

    body = render_pull_request_body(receipt, holds=frozenset())

    assert "Handback initial holds: `security`" in body
    assert "Explicit hard holds: none declared" in body
    assert parse_pull_request_body(body) == receipt


def test_machine_receipt_parser_rejects_missing_or_duplicate_envelopes() -> None:
    body = render_pull_request_body(_receipt())
    with pytest.raises(PolicyViolation, match="one typed"):
        parse_pull_request_body("## Scope\nnone")
    with pytest.raises(PolicyViolation, match="one typed"):
        parse_pull_request_body(body + body)


def test_machine_receipt_parser_normalizes_domain_validation_errors() -> None:
    body = render_pull_request_body(_receipt()).replace(
        '"content_digest":"' + "e" * 64 + '"',
        '"content_digest":"not-a-digest"',
    )

    with pytest.raises(PolicyViolation, match="receipt is invalid"):
        parse_pull_request_body(body)


def test_readiness_validator_binds_receipt_to_exact_pr_head() -> None:
    receipt = _receipt()
    body = render_pull_request_body(receipt)

    assert (
        validate_pull_request_body(body, expected_head_sha=receipt.head_sha) == receipt
    )
    with pytest.raises(PolicyViolation, match="exact PR HEAD"):
        validate_pull_request_body(body, expected_head_sha="f" * 40)


def test_typed_and_label_holds_are_durable_and_union_exactly() -> None:
    body = render_pull_request_body(
        _receipt(), holds=frozenset({HoldKind.P0, HoldKind.SECURITY})
    )
    pull_request = PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch="feat/delivery",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
        body=body,
        labels=("delivery-hold:p1",),
    )

    assert pull_request_holds(pull_request) == frozenset(
        {HoldKind.P0, HoldKind.P1, HoldKind.SECURITY}
    )


def test_legacy_publish_only_is_upgraded_to_a_typed_security_hold() -> None:
    receipt = _receipt()
    pull_request = PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        state="OPEN",
        draft=False,
        mergeable=True,
        body=render_pull_request_body(receipt) + "\nPUBLISH ONLY\n",
    )

    holds = pull_request_holds(pull_request)
    assert holds == frozenset({HoldKind.SECURITY})
    assert '"holds":["security"]' in render_pull_request_body(receipt, holds=holds)


def test_malformed_typed_hold_block_fails_closed() -> None:
    body = render_pull_request_body(_receipt()).replace(
        '"holds":[]', '"holds":["unsupported"]'
    )

    with pytest.raises(PolicyViolation, match="unsupported"):
        parse_pull_request_body(body)
