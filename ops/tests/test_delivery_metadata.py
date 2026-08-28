from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import HandbackReceipt, Scope
from delivery_control.domain.observations import (
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
)
from delivery_control.domain.states import HoldKind
from delivery_control.services.metadata import MetadataRepairService
from delivery_control.services.pr_contract import (
    parse_body_holds,
    render_pull_request_body,
)

BASE = "a" * 40
HEAD = "b" * 40
DIGEST = "c" * 64


def _receipt() -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="ISSUE-1",
        owner_thread_id="owner-1",
        claim_generation=2,
        branch="feat/one",
        worktree_path="/tmp/one",
        base_sha=BASE,
        parent_sha=BASE,
        head_sha=HEAD,
        origin_main_sha=BASE,
        content_digest=DIGEST,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


def _record(receipt: HandbackReceipt) -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id=receipt.lane_id,
        branch=receipt.branch,
        path=Path(receipt.worktree_path),
        status="published",
        scope=receipt.scope,
        base_sha=receipt.base_sha,
        claim_generation=receipt.claim_generation,
        owner_thread_id=receipt.owner_thread_id,
        handed_back_sha=receipt.head_sha,
        handback_claim_generation=receipt.claim_generation,
        handback_valid=True,
        handback_digest=receipt.content_digest,
        handback_origin_main_sha=receipt.origin_main_sha,
    )


class FakeRegistry:
    def __init__(
        self,
        record: RegistrySnapshot,
        *,
        published_record: RegistrySnapshot | None = None,
    ) -> None:
        self.record = record
        self.published_record = published_record

    def list_records(self) -> RegistryInventory:
        return RegistryInventory((self.published_record or self.record,))

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        return self.record if self.record.lane_id == lane_id else None

    def find_published_claim(
        self,
        *,
        lane_id: str,
        branch: str,
        path: Path,
        owner_thread_id: str,
        head_sha: str,
        scope: Scope,
    ) -> RegistrySnapshot | None:
        candidate = self.published_record
        if candidate is None:
            return None
        if (
            candidate.lane_id != lane_id
            or candidate.branch != branch
            or candidate.path.resolve() != path.resolve()
            or candidate.owner_thread_id != owner_thread_id
            or candidate.handed_back_sha != head_sha
            or candidate.scope != scope
        ):
            return None
        return candidate


class FakeGitHub:
    def __init__(self, pull_request: PullRequestSnapshot) -> None:
        self.pull_request = pull_request
        self.updates = 0
        self.ready_calls = 0

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        assert number == self.pull_request.number
        return self.pull_request

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return ("ops/a.py",)

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        assert expected_head_sha == self.pull_request.head_sha
        self.updates += 1
        self.pull_request = replace(self.pull_request, title=title, body=body)
        return self.pull_request

    def mark_ready(self, number: int) -> PullRequestSnapshot:
        self.ready_calls += 1
        self.pull_request = replace(self.pull_request, draft=False)
        return self.pull_request


def _pull_request(
    receipt: HandbackReceipt, *, body: str, draft: bool = False
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        state="OPEN",
        draft=draft,
        mergeable=True,
        title="fix: exact metadata",
        body=body,
    )


def test_metadata_repair_restores_body_and_preserves_durable_hold() -> None:
    receipt = _receipt()
    canonical = render_pull_request_body(receipt, holds=frozenset({HoldKind.SECURITY}))
    github = FakeGitHub(
        _pull_request(receipt, body=canonical.replace("## Scope", "## Changed", 1))
    )

    result = MetadataRepairService(
        registry=FakeRegistry(_record(receipt)),
        query=github,
        command=github,
    ).repair(1)

    assert result.changed
    assert github.updates == 1
    assert github.pull_request.body == canonical
    assert parse_body_holds(github.pull_request.body) == frozenset({HoldKind.SECURITY})


def test_metadata_repair_marks_exact_draft_ready_without_rewriting_code() -> None:
    receipt = _receipt()
    body = render_pull_request_body(receipt)
    github = FakeGitHub(_pull_request(receipt, body=body, draft=True))

    result = MetadataRepairService(
        registry=FakeRegistry(_record(receipt)),
        query=github,
        command=github,
    ).repair(1)

    assert result.changed
    assert github.updates == 0
    assert github.ready_calls == 1
    assert not result.pull_request.draft


def test_metadata_repair_refuses_noncanonical_registry_proof() -> None:
    receipt = _receipt()
    github = FakeGitHub(_pull_request(receipt, body=render_pull_request_body(receipt)))
    mismatched = replace(_record(receipt), status="active")

    with pytest.raises(PolicyViolation, match="exact local receipt"):
        MetadataRepairService(
            registry=FakeRegistry(mismatched),
            query=github,
            command=github,
        ).repair(1)

    assert github.updates == 0


def test_metadata_repair_reconciles_stale_published_generation_from_exact_claim() -> (
    None
):
    original = _receipt()
    current = replace(
        _record(original),
        claim_generation=3,
        handback_claim_generation=3,
        handback_digest="d" * 64,
        published_base_sha="e" * 40,
    )
    github = FakeGitHub(
        replace(
            _pull_request(original, body=render_pull_request_body(original)),
            base_sha="e" * 40,
        )
    )

    result = MetadataRepairService(
        registry=FakeRegistry(_record(original), published_record=current),
        query=github,
        command=github,
    ).repair(1)

    expected = HandbackReceipt(
        lane_id=original.lane_id,
        owner_thread_id=original.owner_thread_id,
        claim_generation=3,
        branch=original.branch,
        worktree_path=original.worktree_path,
        base_sha=original.base_sha,
        parent_sha=original.parent_sha,
        head_sha=original.head_sha,
        origin_main_sha=original.origin_main_sha,
        content_digest="d" * 64,
        scope=original.scope,
    )
    assert result.changed
    assert github.updates == 1
    assert github.pull_request.body == render_pull_request_body(expected)


def test_metadata_repair_accepts_current_claim_after_origin_history_advances() -> None:
    original = _receipt()
    current_origin = "f" * 40
    current = replace(
        _record(original),
        claim_generation=3,
        handback_claim_generation=3,
        handback_digest="d" * 64,
        handback_origin_main_sha=current_origin,
        published_base_sha="e" * 40,
    )
    github = FakeGitHub(
        replace(
            _pull_request(original, body=render_pull_request_body(original)),
            base_sha="e" * 40,
        )
    )

    result = MetadataRepairService(
        registry=FakeRegistry(_record(original), published_record=current),
        query=github,
        command=github,
    ).repair(1)

    expected = HandbackReceipt(
        lane_id=original.lane_id,
        owner_thread_id=original.owner_thread_id,
        claim_generation=3,
        branch=original.branch,
        worktree_path=original.worktree_path,
        base_sha=original.base_sha,
        parent_sha=original.parent_sha,
        head_sha=original.head_sha,
        origin_main_sha=current_origin,
        content_digest="d" * 64,
        scope=original.scope,
    )
    assert result.changed
    assert github.updates == 1
    assert github.pull_request.body == render_pull_request_body(expected)
