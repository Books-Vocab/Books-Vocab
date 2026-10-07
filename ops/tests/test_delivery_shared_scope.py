"""SHARED_SCOPE_FILES is honoured by every delivery-control overlap gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.demand_issues import (
    ISSUE_INTAKE_SCHEMA,
    IssueIntakeRequest,
)
from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryCollisionClaim,
    RegistryCollisionInventory,
)
from delivery_control.services.correlation import collision_keys
from delivery_control.services.issue_admission import (
    assert_candidate_scope_available,
    assert_issue_intake_available,
)
from lib.worktree_scope import SHARED_SCOPE_FILES, exclusive_paths

SHARED = "docs/registry.yml"


def _claim(*paths: str) -> RegistryCollisionClaim:
    return RegistryCollisionClaim(
        lane_id="lane-x", branch="feat/x", scope=Scope.from_paths(modify=paths)
    )


def _pull_request(number: int = 9) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://example.test/pull/{number}",
        branch="feat/other",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
        title="t",
        body="b",
    )


def _candidate(
    scope: Scope,
    *,
    claims: tuple[RegistryCollisionClaim, ...] = (),
    pull_requests: tuple[PullRequestSnapshot, ...] = (),
    observed: tuple[str, ...] = (),
) -> None:
    assert_candidate_scope_available(
        scope=scope,
        demand_issues=(),
        registry=RegistryCollisionInventory(records=claims),
        pull_requests=PullRequestInventory(records=pull_requests),
        changed_paths=lambda _number: observed,
    )


def _intake(
    scope: Scope,
    *,
    claims: tuple[RegistryCollisionClaim, ...] = (),
    pull_requests: tuple[PullRequestSnapshot, ...] = (),
    observed: tuple[str, ...] = (),
) -> None:
    request = IssueIntakeRequest.from_payload(
        {
            "schema": ISSUE_INTAKE_SCHEMA,
            "title": "A bounded raw Issue",
            "body": "A bounded report",
            "labels": ["bug"],
            "source": "scout",
            "provenance": "fixture:issue-intake",
            "severity": "P2",
            "priority": 7,
            "acceptance": ["The raw Issue is read back exactly."],
            "scope": scope.to_payload(),
            "operator": "supervisor",
        }
    )
    assert_issue_intake_available(
        request=request,
        demand_issues=(),
        registry=RegistryCollisionInventory(records=claims),
        pull_requests=PullRequestInventory(records=pull_requests),
        changed_paths=lambda _number: observed,
    )


def test_receipt_scope_keeps_shared_files_exactly() -> None:
    scope = Scope.from_paths(modify=(SHARED, "ops/a.py"))

    assert scope.paths == ("docs/registry.yml", "ops/a.py")
    assert exclusive_paths(scope.paths) == {"ops/a.py"}
    # A lane still declares, and may change, the shared file (hand-back exactness).
    assert scope.to_payload()["files"][0]["path"] == SHARED
    assert scope.allows_changed_paths((SHARED,))
    assert set(scope.paths) & SHARED_SCOPE_FILES == {SHARED}


def test_candidate_admission_allows_shared_overlap_with_registry_claim() -> None:
    scope = Scope.from_paths(modify=(SHARED, "ops/a.py"))
    _candidate(scope, claims=(_claim(SHARED, "ops/z.py"),))


def test_candidate_admission_still_rejects_exclusive_overlap() -> None:
    scope = Scope.from_paths(modify=(SHARED, "ops/a.py"))
    with pytest.raises(PolicyViolation, match="active registry lane"):
        _candidate(scope, claims=(_claim(SHARED, "ops/a.py"),))


def test_candidate_admission_ignores_shared_file_in_open_pr() -> None:
    scope = Scope.from_paths(modify=(SHARED, "ops/a.py"))
    _candidate(scope, pull_requests=(_pull_request(),), observed=(SHARED, "ops/z.py"))
    with pytest.raises(PolicyViolation, match="open PR #9"):
        _candidate(
            scope, pull_requests=(_pull_request(),), observed=(SHARED, "ops/a.py")
        )


def test_issue_intake_allows_shared_overlap_but_not_exclusive_overlap() -> None:
    scope = Scope.from_paths(modify=(SHARED, "ops/a.py"))
    _intake(scope, claims=(_claim(SHARED, "ops/z.py"),))
    _intake(scope, pull_requests=(_pull_request(),), observed=(SHARED, "ops/z.py"))
    with pytest.raises(PolicyViolation, match="overlaps active registry"):
        _intake(scope, claims=(_claim(SHARED, "ops/a.py"),))
    with pytest.raises(PolicyViolation, match="open PR #9"):
        _intake(scope, pull_requests=(_pull_request(),), observed=("ops/a.py",))


def test_collision_keys_ignore_shared_files_only_overlap() -> None:
    assert collision_keys({"lane:a": {SHARED, "ops/a.py"}, "lane:b": {SHARED}}) == set()
    assert collision_keys(
        {"lane:a": {SHARED, "ops/a.py"}, "lane:b": {SHARED, "ops/a.py"}}
    ) == {"lane:a", "lane:b"}
