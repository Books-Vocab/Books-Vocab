from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import worktree_registry as registry
from delivery_control.domain.models import CheckStatus, HandbackReceipt, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
    MergeQueueEntrySnapshot,
    PullRequestInventory,
    PullRequestSnapshot,
)
from delivery_control.domain.states import HoldKind
from delivery_control.services.pr_contract import render_pull_request_body
from worktree_reanchor_core import lifecycle_proof, registry_ops
from worktree_reanchor_core.errors import ReanchorRefused

BASE = "1" * 40
HEAD = "3" * 40
LANE = "DIRECT-ABANDONED-PR-RECOVERY"
BRANCH = "debug/abandoned-pr-recovery"
OWNER = "owner-thread"
TARGET_SCOPE = Scope.from_paths(modify=("ops/example.py",))


def _record(tmp_path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "branch": BRANCH,
        "path": str(tmp_path / "owner-worktree"),
        "intent": "recover one exact abandoned PR",
        "base": BASE,
        "base_sha": BASE,
        "status": "abandoned",
        "external_ids": [LANE],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": "ops/example.py", "operation": "modify"}],
        },
        "codex_thread_id": OWNER,
        "delegated": True,
        "claim_generation": 1,
        "handed_back_at": "2026-09-15T00:00:00Z",
        "handed_back_sha": HEAD,
        "handback_claim_generation": 1,
    }
    record["handback_seal"] = registry._seal_with_digest(
        registry._seal_body(
            record,
            base_sha=BASE,
            tip_sha=HEAD,
            outcomes=[{"name": "focused", "status": "success"}],
            handed_back_at="2026-09-15T00:00:00Z",
            origin_main_sha=BASE,
        )
    )
    return record


def test_abandoned_recovery_creates_new_published_generation_and_keeps_history(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    registry.save_state(
        state_path,
        {"schema": registry.SCHEMA, "records": [_record(tmp_path)]},
    )

    preflight = registry_ops.preflight_abandoned(
        state_path=state_path,
        lane_id=LANE,
        branch=BRANCH,
        owner_thread_id=OWNER,
        claim_generation=1,
        expected_remote_head=HEAD,
        target=tmp_path / "owner-worktree",
    )
    recovered = registry_ops.register_recovered_abandoned(
        state_path=state_path,
        preflight_result=preflight,
        target=tmp_path / "owner-worktree",
        lane_id=LANE,
        claim_generation=1,
    )

    records = registry.load_state(state_path)["records"]
    assert len(records) == 2
    assert records[0]["status"] == "abandoned"
    assert recovered["status"] == "published"
    assert recovered["claim_generation"] == 2
    assert recovered["handback_claim_generation"] == 2
    assert recovered["handed_back_sha"] == HEAD
    assert registry._has_valid_stored_handback(recovered)


def test_abandoned_recovery_rejects_another_live_claim(tmp_path: Path) -> None:
    original = _record(tmp_path)
    live = dict(original)
    live["status"] = "published"
    live["claim_generation"] = 2
    state_path = tmp_path / "registry.json"
    registry.save_state(
        state_path,
        {"schema": registry.SCHEMA, "records": [original, live]},
    )

    with pytest.raises(ReanchorRefused, match="already owned|external reference"):
        registry_ops.preflight_abandoned(
            state_path=state_path,
            lane_id=LANE,
            branch=BRANCH,
            owner_thread_id=OWNER,
            claim_generation=1,
            expected_remote_head=HEAD,
            target=tmp_path / "owner-worktree",
        )


class _GitHub:
    def __init__(self, pull_request: PullRequestSnapshot) -> None:
        self.pull_request = pull_request

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory((self.pull_request,))

    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory((self.pull_request,))

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        return CheckSnapshot(
            status=CheckStatus.FAILURE,
            head_sha=HEAD,
            observed_at=datetime(2026, 9, 15, tzinfo=UTC),
            names=("required",),
        )

    def merge_queue_entry_snapshot(
        self, pull_request_id: str
    ) -> MergeQueueEntrySnapshot | None:
        return None


def _pull_request(*, owner: str = OWNER, body_holds=frozenset()) -> PullRequestSnapshot:
    receipt = HandbackReceipt(
        lane_id=LANE,
        owner_thread_id=owner,
        claim_generation=1,
        branch=BRANCH,
        worktree_path="/tmp/owner-worktree",
        base_sha=BASE,
        parent_sha="2" * 40,
        head_sha=HEAD,
        origin_main_sha=BASE,
        content_digest="4" * 64,
        scope=TARGET_SCOPE,
    )
    return PullRequestSnapshot(
        number=1930,
        url="https://example.test/pull/1930",
        branch=BRANCH,
        base_sha=BASE,
        head_sha=HEAD,
        state="OPEN",
        draft=False,
        mergeable=True,
        base_branch="main",
        node_id="PR_1930",
        body=render_pull_request_body(receipt, holds=body_holds),
    )


def test_abandoned_pr_proof_requires_exact_owner_and_allows_lane_local_failure() -> (
    None
):
    pull_request = _pull_request()
    proof = lifecycle_proof.verify_abandoned_pr_lifecycle(
        _GitHub(pull_request),
        lane_id=LANE,
        branch=BRANCH,
        owner_thread_id=OWNER,
        claim_generation=1,
        expected_base_sha=BASE,
        expected_remote_head=HEAD,
        recorded_base_sha=BASE,
        declared_scope=(("ops/example.py", "modify"),),
        handback_digest="4" * 64,
    )

    assert proof.pull_request_number == 1930
    assert proof.required_status is CheckStatus.FAILURE


def test_abandoned_pr_proof_rejects_owner_mismatch_and_hard_hold() -> None:
    with pytest.raises(ReanchorRefused, match="owner"):
        lifecycle_proof.verify_abandoned_pr_lifecycle(
            _GitHub(_pull_request(owner="other-owner")),
            lane_id=LANE,
            branch=BRANCH,
            owner_thread_id=OWNER,
            claim_generation=1,
            expected_base_sha=BASE,
            expected_remote_head=HEAD,
            recorded_base_sha=BASE,
            declared_scope=(("ops/example.py", "modify"),),
            handback_digest="4" * 64,
        )
    with pytest.raises(ReanchorRefused, match="hard hold"):
        lifecycle_proof.verify_abandoned_pr_lifecycle(
            _GitHub(_pull_request(body_holds={HoldKind.SECURITY})),
            lane_id=LANE,
            branch=BRANCH,
            owner_thread_id=OWNER,
            claim_generation=1,
            expected_base_sha=BASE,
            expected_remote_head=HEAD,
            recorded_base_sha=BASE,
            declared_scope=(("ops/example.py", "modify"),),
            handback_digest="4" * 64,
        )
