from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    InventoryProblem,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.domain.states import (
    LaneDecision,
    LaneState,
    NextAction,
)
from delivery_control.services.inspect import LaneInspection
from delivery_control.services.isolation import project_isolation


def _sources(*, problems=(), pull_requests=(), records=(), physical=()):
    return SimpleNamespace(
        source_problems=tuple(problems),
        pull_requests=tuple(pull_requests),
        records=tuple(records),
        physical=tuple(physical),
    )


def _lane(*, registry=None, state=LaneState.UNKNOWN, pull_requests=()):
    return LaneInspection(
        key="lane",
        registry=registry,
        physical=None,
        snapshot=None,
        pull_requests=tuple(pull_requests),
        decision=LaneDecision(state, NextAction.INSPECT, "test"),
    )


def _registry(*, status="active", branch="feat/legacy"):
    return RegistrySnapshot(
        lane_id=branch,
        branch=branch,
        path=Path("/tmp") / branch.replace("/", "-"),
        status=status,
        scope=Scope.from_paths(modify=("ops/legacy.py",)),
        base_sha="a" * 40,
        claim_generation=0,
    )


def test_registry_source_history_without_runtime_assets_is_quarantined() -> None:
    summary = project_isolation(
        sources=_sources(
            problems=(InventoryProblem("registry", "feat/legacy", "malformed"),)
        ),
        lanes=(),
    )

    assert summary.quarantined_source_problems == 1


def test_active_missing_worktree_is_quarantined_but_not_deleted() -> None:
    summary = project_isolation(
        sources=_sources(),
        lanes=(_lane(registry=_registry()),),
    )

    assert summary.quarantined_blocked_lanes == 1
    assert summary.quarantined_lanes == 1


def test_terminal_residue_without_physical_worktree_is_quarantined() -> None:
    summary = project_isolation(
        sources=_sources(),
        lanes=(_lane(registry=_registry(status="merged"), state=LaneState.TERMINAL_CLEANUP),),
    )

    assert summary.quarantined_terminal_cleanup == 1


def test_security_hold_open_pr_is_quarantined_outside_merge_reservoir() -> None:
    pull_request = PullRequestSnapshot(
        number=1376,
        url="https://example.test/pull/1376",
        branch="debug/issue-1373-env-drift-path-injection-20260821",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
        body="PUBLISH ONLY: security hold pending",
    )

    summary = project_isolation(
        sources=_sources(pull_requests=(pull_request,)),
        lanes=(_lane(pull_requests=(pull_request,)),),
    )

    assert summary.quarantined_open_prs == 1
