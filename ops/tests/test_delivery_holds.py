from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import HandbackReceipt, Scope
from delivery_control.domain.observations import PullRequestSnapshot
from delivery_control.domain.states import HoldKind
from delivery_control.services.holds import HoldService
from delivery_control.services.pr_contract import (
    pull_request_holds,
    render_pull_request_body,
)


def _receipt() -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="ISSUE-1",
        owner_thread_id="thread-1",
        claim_generation=1,
        branch="feat/one",
        worktree_path="/tmp/one",
        base_sha="a" * 40,
        parent_sha="a" * 40,
        head_sha="b" * 40,
        origin_main_sha="a" * 40,
        content_digest="c" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


class FakeGitHub:
    def __init__(self, pull_request: PullRequestSnapshot) -> None:
        self.pull_request = pull_request
        self.update_calls = 0

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        assert number == self.pull_request.number
        return self.pull_request

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        assert number == self.pull_request.number
        assert expected_head_sha == self.pull_request.head_sha
        self.update_calls += 1
        self.pull_request = replace(self.pull_request, title=title, body=body)
        return self.pull_request


def _pull_request(
    *, holds: frozenset[HoldKind], labels: tuple[str, ...] = ()
) -> PullRequestSnapshot:
    receipt = _receipt()
    return PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        state="OPEN",
        draft=False,
        mergeable=True,
        title="fix: one",
        body=render_pull_request_body(receipt, holds=holds),
        labels=labels,
    )


def test_hold_reconciliation_adds_a_typed_durable_hold() -> None:
    github = FakeGitHub(_pull_request(holds=frozenset()))

    result = HoldService(query=github, command=github).reconcile(
        number=1,
        holds=frozenset({HoldKind.P1}),
        clear_all=False,
    )

    assert result.holds == frozenset({HoldKind.P1})
    assert pull_request_holds(result.pull_request) == frozenset({HoldKind.P1})
    assert github.update_calls == 1


def test_hold_reconciliation_clears_body_only_after_explicit_clear_all() -> None:
    github = FakeGitHub(_pull_request(holds=frozenset({HoldKind.SECURITY})))

    result = HoldService(query=github, command=github).reconcile(
        number=1,
        holds=frozenset(),
        clear_all=True,
    )

    assert result.holds == frozenset()
    assert pull_request_holds(result.pull_request) == frozenset()


def test_hold_clear_refuses_durable_label_before_any_body_mutation() -> None:
    github = FakeGitHub(
        _pull_request(
            holds=frozenset({HoldKind.SECURITY}),
            labels=("delivery-hold:security",),
        )
    )

    with pytest.raises(PolicyViolation, match="labels remain"):
        HoldService(query=github, command=github).reconcile(
            number=1,
            holds=frozenset(),
            clear_all=True,
        )
    assert github.update_calls == 0


def test_hold_reconciliation_refuses_to_omit_a_durable_label() -> None:
    github = FakeGitHub(
        _pull_request(
            holds=frozenset({HoldKind.P0, HoldKind.SECURITY}),
            labels=("delivery-hold:security",),
        )
    )

    with pytest.raises(PolicyViolation, match="omit"):
        HoldService(query=github, command=github).reconcile(
            number=1,
            holds=frozenset({HoldKind.P0}),
            clear_all=False,
        )
    assert github.update_calls == 0
