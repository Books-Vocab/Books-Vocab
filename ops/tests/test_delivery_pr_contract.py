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
    IssueLinks,
    parse_body_issues,
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
        '- Handback outcome 1: `{"name":"tests","status":"success","summary":"green"}`'
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


# 2309-scale integration PR: many issues closed, a few only referenced.
_WIDE = IssueLinks(closes=tuple(range(2064, 2049, -1)), refs=(2026, 2045, 2047))


def test_empty_issue_links_leave_the_body_byte_identical() -> None:
    body = render_pull_request_body(_receipt())

    assert render_pull_request_body(_receipt(), issues=IssueLinks()) == body
    assert "## Issues" not in body
    assert parse_body_issues(body) == IssueLinks()


def test_issues_section_renders_one_keyword_per_line_in_canonical_order() -> None:
    body = render_pull_request_body(
        _receipt(), issues=IssueLinks(closes=(9, 3, 3), refs=(7,))
    )

    assert "\n## Issues\nCloses #3\nCloses #9\nRefs #7\n\n" in body
    assert body.index("## Impact") < body.index("## Issues") < body.index("<!--")
    assert parse_body_issues(body) == IssueLinks(closes=(3, 9), refs=(7,))
    assert parse_pull_request_body(body) == _receipt()


def test_wide_integration_body_passes_readiness_with_exactly_one_receipt() -> None:
    receipt = _receipt()
    body = render_pull_request_body(receipt, issues=_WIDE)

    assert body.count("Closes #") == 15 and body.count("Refs #") == 3
    assert body.count("kg.delivery.receipt.v1") == 1
    assert (
        validate_pull_request_body(body, expected_head_sha=receipt.head_sha) == receipt
    )
    assert parse_body_issues(body) == _WIDE
    with pytest.raises(PolicyViolation, match="one typed"):
        parse_pull_request_body(body + body)


def test_readiness_accepts_bodies_with_and_without_the_section() -> None:
    receipt = _receipt()
    for issues in (IssueLinks(), IssueLinks(closes=(1,)), IssueLinks(refs=(2,))):
        body = render_pull_request_body(receipt, issues=issues)
        assert (
            validate_pull_request_body(body, expected_head_sha=receipt.head_sha)
            == receipt
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.replace("Closes #3", "Closes #3, #4"),
        lambda b: b.replace("Closes #3", "Fixes #3"),
        lambda b: b.replace("Closes #3", "Closes #0"),
        lambda b: b.replace("Closes #3", "Closes #3\nRefs #3"),
        lambda b: b + "\n## Issues\nRefs #8\n",
    ],
)
def test_malformed_issues_section_fails_closed(mutate) -> None:
    receipt = _receipt()
    body = mutate(render_pull_request_body(receipt, issues=IssueLinks(closes=(3,))))

    with pytest.raises(PolicyViolation, match="Issues"):
        validate_pull_request_body(body, expected_head_sha=receipt.head_sha)


def test_issue_links_reject_overlap_and_non_positive_numbers() -> None:
    with pytest.raises(PolicyViolation, match="Issues"):
        IssueLinks(closes=(5,), refs=(5,))
    with pytest.raises(PolicyViolation, match="Issues"):
        IssueLinks(closes=(0,))


def test_keywords_outside_the_issues_section_are_ignored() -> None:
    body = render_pull_request_body(_receipt()) + "\nCloses #99\n"

    assert parse_body_issues(body) == IssueLinks()


def test_external_ids_yield_closing_issues_only_for_issue_references() -> None:
    links = IssueLinks.from_external_ids(
        (
            "lane-issue-mgmt-w4",
            "#2392",
            "https://github.com/Books-Vocab/Books-Vocab/issues/2393/",
            "https://example.test/pull/5",
        )
    )

    assert links == IssueLinks(closes=(2392, 2393))


@pytest.mark.parametrize(
    ("external_id", "number"),
    [("2309", 2309), ("issue-2310", 2310), ("issue:2311", 2311), ("ISSUE-1", 1)],
)
def test_external_ids_share_the_claim_rule_for_bare_forms(
    external_id: str, number: int
) -> None:
    assert IssueLinks.from_external_ids((external_id,)) == IssueLinks(closes=(number,))


@pytest.mark.parametrize(
    "external_id",
    [
        "https://github.com/o/r/issues/2393/events",
        "https://x/issues/12abc",
        "ftp://github.com/o/r/issues/5",
        "/o/r/issues/5",
        "github.com/o/r/issues/5",
        "https://github.com/o/r/pull/5",
    ],
)
def test_malformed_issue_urls_never_close_anything(external_id: str) -> None:
    assert IssueLinks.from_external_ids((external_id,)) == IssueLinks()


# --- issue-named branches must link their issue (#2654) ---------------------


@pytest.mark.parametrize(
    ("branch", "number"),
    [
        ("debug/issue-2463-wave", 2463),
        ("fix/issue-7", 7),
        ("feat/issue-12-extra-words", 12),
        ("issue-5", 5),
    ],
)
def test_issue_links_from_branch_name(branch: str, number: int) -> None:
    assert IssueLinks.from_branch(branch) == IssueLinks(closes=(number,))


@pytest.mark.parametrize(
    "branch",
    ["feat/delivery", "fix/tissue-3", "fix/issue-x", "fix/issue-0", "issues-4"],
)
def test_issue_links_from_branch_ignores_non_issue_branches(branch: str) -> None:
    assert IssueLinks.from_branch(branch) == IssueLinks()


def test_readiness_rejects_issue_named_branch_without_issue_link() -> None:
    receipt = replace(_receipt(), branch="debug/issue-42-fix")
    body = render_pull_request_body(receipt)

    with pytest.raises(PolicyViolation, match="issue-42.*Closes #42 or Refs #42"):
        validate_pull_request_body(body, expected_head_sha=receipt.head_sha)


@pytest.mark.parametrize("issues", [IssueLinks(closes=(42,)), IssueLinks(refs=(42,))])
def test_readiness_accepts_issue_named_branch_with_closes_or_refs(
    issues: IssueLinks,
) -> None:
    receipt = replace(_receipt(), branch="debug/issue-42-fix")
    body = render_pull_request_body(receipt, issues=issues)

    assert (
        validate_pull_request_body(body, expected_head_sha=receipt.head_sha) == receipt
    )


def test_readiness_checks_the_actual_head_ref_too() -> None:
    receipt = _receipt()
    body = render_pull_request_body(receipt)

    with pytest.raises(PolicyViolation, match="issue-9"):
        validate_pull_request_body(
            body, expected_head_sha=receipt.head_sha, head_ref="fix/issue-9"
        )
