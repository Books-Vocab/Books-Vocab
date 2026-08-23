# ruff: noqa: E402

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import CompareAndSwapConflict
from delivery_control.domain.models import HandbackReceipt, Scope
from delivery_control.domain.observations import (
    FileChange,
    FileOperation,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.services.publish import PublishService
from delivery_control.services.publish_head_readback import (
    wait_for_pull_request_head,
)
from delivery_control.services.publish_preflight import PublicationContext

BASE = "a" * 40
OLD_HEAD = "b" * 40
HEAD = "c" * 40


def _receipt() -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="DIRECT-HEAD-READBACK",
        owner_thread_id="thread-1",
        claim_generation=1,
        branch="debug/example",
        worktree_path="/tmp/delivery-head-readback",
        base_sha=BASE,
        parent_sha=BASE,
        head_sha=HEAD,
        origin_main_sha=BASE,
        content_digest="d" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


def _snapshot(head_sha: str) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=12,
        url="https://example.test/pull/12",
        branch="debug/example",
        base_sha="a" * 40,
        head_sha=head_sha,
        state="OPEN",
        draft=False,
        mergeable=True,
    )


def test_head_readback_converges_after_transient_github_lag() -> None:
    old = _snapshot("b" * 40)
    current = _snapshot("c" * 40)
    observations = iter((old, old, current))
    sleeps: list[float] = []

    result = wait_for_pull_request_head(
        lambda _number: next(observations),
        number=12,
        expected_head_sha=current.head_sha,
        retry_delays=(0.1, 0.2),
        sleeper=sleeps.append,
    )

    assert result == current
    assert sleeps == [0.1, 0.2]


def test_head_readback_fails_closed_on_stable_external_drift() -> None:
    observed = _snapshot("b" * 40)
    sleeps: list[float] = []

    with pytest.raises(CompareAndSwapConflict, match="did not converge"):
        wait_for_pull_request_head(
            lambda _number: observed,
            number=12,
            expected_head_sha="c" * 40,
            retry_delays=(0.1, 0.2),
            sleeper=sleeps.append,
        )

    assert sleeps == [0.1, 0.2]


def test_head_readback_does_not_retry_query_errors() -> None:
    sleeps: list[float] = []

    def fail(_number: int) -> PullRequestSnapshot:
        raise RuntimeError("API unavailable")

    with pytest.raises(RuntimeError, match="API unavailable"):
        wait_for_pull_request_head(
            fail,
            number=12,
            expected_head_sha="c" * 40,
            sleeper=sleeps.append,
        )

    assert sleeps == []


def test_publish_waits_for_existing_pr_head_after_branch_push() -> None:
    receipt = _receipt()
    stale = PullRequestSnapshot(
        number=12,
        url="https://example.test/pull/12",
        branch=receipt.branch,
        base_sha=BASE,
        head_sha=OLD_HEAD,
        state="OPEN",
        draft=False,
        mergeable=True,
        title="old title",
        body="old body",
    )
    current = replace(stale, head_sha=HEAD)
    worktree = WorktreeSnapshot(
        path=Path(receipt.worktree_path),
        branch=receipt.branch,
        base_sha=BASE,
        head_sha=HEAD,
        parent_sha=BASE,
        clean=True,
        changes=(FileChange(FileOperation.MODIFY, "ops/a.py"),),
    )
    context = PublicationContext(
        registry=RegistrySnapshot(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=worktree.path,
            status="active",
            scope=receipt.scope,
            base_sha=BASE,
            claim_generation=1,
        ),
        worktree=worktree,
        pull_request=stale,
        remote_sha=OLD_HEAD,
    )

    class Preflight:
        def check(self, _receipt: HandbackReceipt) -> PublicationContext:
            return context

    class Git:
        def push_branch(self, **kwargs: object) -> str:
            assert kwargs["expected_local_sha"] == HEAD
            return HEAD

    class GitHub:
        def __init__(self) -> None:
            self.reads = iter((stale, current))
            self.current = current
            self.update_calls = 0

        def get_pull_request(self, _number: int) -> PullRequestSnapshot:
            return next(self.reads, self.current)

        def branch_is_protected(self, _branch: str) -> bool:
            return False

        def update_pull_request(self, **kwargs: object) -> PullRequestSnapshot:
            self.update_calls += 1
            self.current = replace(
                self.current,
                title=kwargs["title"],
                body=kwargs["body"],
            )
            return self.current

        def trigger_readiness(self, **_kwargs: object) -> tuple[str, ...]:
            return ("readiness",)

    github = GitHub()
    service = PublishService(
        preflight=Preflight(),
        git=Git(),
        github_query=github,
        github_command=github,
        github_workflow=github,
    )

    result = service.publish(receipt=receipt, title="fix: head readback")

    assert result.pull_request.head_sha == HEAD
    assert result.readiness_dispatch == ("readiness",)
    assert github.update_calls == 1
