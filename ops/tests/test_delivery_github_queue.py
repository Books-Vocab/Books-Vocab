from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_queue import GitHubQueueGraphQLAdapter
from delivery_control.domain.errors import CompareAndSwapConflict
from delivery_control.ports.process import CommandResult

BASE = "a" * 40
HEAD = "b" * 40
PR_ID = "PR_kwDOexample"


class StaticRunner:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return CommandResult(argv, 0, json.dumps(self.payloads.pop(0)), "")


def _state(
    *,
    base_branch: str = "main",
    base_sha: str = BASE,
    head_sha: str = HEAD,
    state: str = "OPEN",
    entry_id: str | None = None,
) -> dict[str, object]:
    return {
        "data": {
            "node": {
                "id": PR_ID,
                "baseRefName": base_branch,
                "baseRefOid": base_sha,
                "headRefOid": head_sha,
                "state": state,
                "mergeQueueEntry": {"id": entry_id} if entry_id else None,
            }
        }
    }


def _enqueued(entry_id: str = "MQE_1") -> dict[str, object]:
    return {
        "data": {
            "enqueuePullRequest": {"mergeQueueEntry": {"id": entry_id}}
        }
    }


def test_native_enqueue_uses_expected_head_and_accepts_main_advancing() -> None:
    runner = StaticRunner(
        [_state(), _enqueued(), _state(base_sha="c" * 40, entry_id="MQE_1")]
    )

    GitHubQueueGraphQLAdapter(repo=Path("/repo"), runner=runner).enqueue(
        pull_request_id=PR_ID,
        expected_base_sha=BASE,
        expected_head_sha=HEAD,
    )

    mutation = next(
        call for call in runner.calls if "enqueuePullRequest" in " ".join(call)
    )
    assert f"expectedHeadOid={HEAD}" in mutation
    assert all(call[:3] != ("gh", "pr", "merge") for call in runner.calls)


def test_native_enqueue_is_idempotent_for_exact_existing_queue_entry() -> None:
    runner = StaticRunner([_state(entry_id="MQE_existing")])

    GitHubQueueGraphQLAdapter(repo=Path("/repo"), runner=runner).enqueue(
        pull_request_id=PR_ID,
        expected_base_sha=BASE,
        expected_head_sha=HEAD,
    )

    assert len(runner.calls) == 1


def test_native_enqueue_dequeues_if_target_changes_during_mutation() -> None:
    runner = StaticRunner(
        [
            _state(),
            _enqueued(),
            _state(base_branch="release", entry_id="MQE_1"),
            {"data": {"dequeuePullRequest": {"clientMutationId": None}}},
            _state(base_branch="release"),
        ]
    )

    with pytest.raises(CompareAndSwapConflict, match="during native enqueue"):
        GitHubQueueGraphQLAdapter(repo=Path("/repo"), runner=runner).enqueue(
            pull_request_id=PR_ID,
            expected_base_sha=BASE,
            expected_head_sha=HEAD,
        )

    assert any("dequeuePullRequest" in " ".join(call) for call in runner.calls)
    assert all(call[:3] != ("gh", "pr", "merge") for call in runner.calls)


def test_native_enqueue_fails_closed_if_target_is_already_terminal() -> None:
    runner = StaticRunner(
        [_state(), _enqueued(), _state(base_branch="release", state="MERGED")]
    )

    with pytest.raises(CompareAndSwapConflict, match="during native enqueue"):
        GitHubQueueGraphQLAdapter(repo=Path("/repo"), runner=runner).enqueue(
            pull_request_id=PR_ID,
            expected_base_sha=BASE,
            expected_head_sha=HEAD,
        )

    assert all(call[:3] != ("gh", "pr", "merge") for call in runner.calls)
