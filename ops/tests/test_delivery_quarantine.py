from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import HandbackReceipt, Scope
from delivery_control.domain.observations import (
    PullRequestInventory,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.services.pr_contract import render_pull_request_body
from delivery_control.services.quarantine import QuarantineService

BASE = "a" * 40
PR_BASE = "b" * 40
HEAD = "c" * 40
BRANCH = "debug/quarantine"
WORKTREE = "/tmp/quarantine-worktree"
LANE = "DIRECT-QUARANTINE-1"
OWNER = "owner-thread-1"
SCOPE = Scope.from_paths(modify=("ops/declared.py",))


def _receipt() -> HandbackReceipt:
    return HandbackReceipt.from_payload(
        {
            "schema": "kg.delivery.handback.v1",
            "lane_id": LANE,
            "owner_thread_id": OWNER,
            "claim_generation": 2,
            "branch": BRANCH,
            "worktree_path": WORKTREE,
            "base_sha": BASE,
            "parent_sha": BASE,
            "head_sha": HEAD,
            "origin_main_sha": BASE,
            "content_digest": "d" * 64,
            "scope": SCOPE.to_payload(),
            "scope_digest": SCOPE.digest,
            "validation": [{"name": "focused", "status": "passed"}],
            "initial_holds": [],
        }
    )


class FakeRegistry:
    def __init__(self, receipt: HandbackReceipt) -> None:
        self.record = RegistrySnapshot(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=Path(receipt.worktree_path),
            status="published",
            scope=receipt.scope,
            base_sha=receipt.base_sha,
            claim_generation=receipt.claim_generation,
            external_ids=(receipt.lane_id,),
            owner_thread_id=receipt.owner_thread_id,
            handed_back_sha=receipt.head_sha,
            handback_claim_generation=receipt.claim_generation,
            handback_valid=True,
            handback_digest=receipt.content_digest,
            handback_origin_main_sha=receipt.origin_main_sha,
        )

    def find_exact_claim(self, **kwargs: object) -> RegistrySnapshot | None:
        if (
            kwargs["lane_id"] == self.record.lane_id
            and kwargs["branch"] == self.record.branch
            and kwargs["claim_generation"] == self.record.claim_generation
        ):
            return self.record
        return None

    def resolve(self, lane_id: str, disposition: str, **kwargs: object) -> None:
        assert lane_id == self.record.lane_id
        assert disposition == "abandoned"
        self.record = replace(self.record, status="abandoned")


class FakeGit:
    def __init__(self) -> None:
        self.remote = HEAD
        self.local = None
        self.actions: list[str] = []

    def list_worktrees(self):
        return ()

    def local_branch_sha(self, branch: str):
        return self.local

    def remote_branch_sha(self, branch: str):
        return self.remote

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert expected_head_sha == HEAD
        self.actions.append("delete-remote")
        self.remote = None


class FakeGitHub:
    def __init__(self, receipt: HandbackReceipt, *, holds: tuple[str, ...] = ()) -> None:
        self.receipt = receipt
        self.pull_request = PullRequestSnapshot(
            number=7,
            url="https://example.test/pull/7",
            branch=BRANCH,
            base_sha=PR_BASE,
            head_sha=HEAD,
            state="OPEN",
            draft=False,
            mergeable=True,
            body=render_pull_request_body(receipt),
            node_id="PR_7",
            labels=holds,
        )
        self.actual_paths = ("ops/declared.py", "ops/accidental.py")
        self.closed = False

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        return self.pull_request

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory((self.pull_request,))

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return self.actual_paths

    def merge_queue_entry_snapshot(self, pull_request_id: str):
        return None

    def close_pull_request(self, **kwargs: object) -> PullRequestSnapshot:
        self.closed = True
        self.pull_request = replace(self.pull_request, state="CLOSED")
        return self.pull_request

    def reopen_pull_request(self, **kwargs: object) -> PullRequestSnapshot:
        self.closed = False
        self.pull_request = replace(self.pull_request, state="OPEN")
        return self.pull_request


def _service(*, holds: tuple[str, ...] = ()):
    receipt = _receipt()
    registry = FakeRegistry(receipt)
    git = FakeGit()
    github = FakeGitHub(receipt, holds=holds)
    return (
        QuarantineService(
            registry_query=registry,
            registry_command=registry,
            git_query=git,
            git_command=git,
            github_query=github,
            github_command=github,
        ),
        registry,
        git,
        github,
    )


def test_quarantine_closes_exact_malformed_pr_and_releases_remote_branch() -> None:
    service, registry, git, github = _service()

    result = service.quarantine(pull_request_number=7)

    assert result.pull_request_state == "CLOSED"
    assert result.registry_status == "abandoned"
    assert result.remote_branch_absent
    assert result.mismatches == ("pr-base-differs-from-receipt", "pr-scope-differs-from-receipt")
    assert github.closed
    assert git.actions == ["delete-remote"]
    assert registry.record.status == "abandoned"


def test_quarantine_refuses_hard_hold_before_close() -> None:
    service, _, _, github = _service(holds=("delivery-hold:p1",))

    with pytest.raises(PolicyViolation, match="hard hold"):
        service.quarantine(pull_request_number=7)

    assert not github.closed
