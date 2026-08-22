from __future__ import annotations

import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.adapters.github_queue import (
    GitHubQueueGraphQLAdapter,
)
from delivery_control.ports.process import CommandResult


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0)


def _state(
    *,
    pull_request_id: str = "PR_kwDOexample",
    number: int = 12,
    head: str = "b" * 40,
    entry_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": pull_request_id,
        "number": number,
        "baseRefName": "main",
        "baseRefOid": "a" * 40,
        "headRefOid": head,
        "body": "body",
        "state": "OPEN",
        "mergeQueueEntry": (
            {"id": entry_id, "enqueuedAt": "2026-08-22T12:00:00Z"} if entry_id else None
        ),
    }


def _page(*nodes: dict[str, object]) -> dict[str, object]:
    return {
        "data": {
            "repository": {
                "pullRequests": {
                    "nodes": list(nodes),
                    "pageInfo": {"hasNextPage": False, "endCursor": "end"},
                }
            }
        }
    }


def _node_payload(*, number: int = 12, head: str = "b" * 40) -> dict[str, object]:
    return {
        "id": "PR_kwDOexample",
        "number": number,
        "url": f"https://example.test/pull/{number}",
        "headRefName": "feat/one",
        "baseRefName": "main",
        "baseRefOid": "a" * 40,
        "headRefOid": head,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "title": "fix: one",
        "body": "body",
        "autoMergeRequest": None,
    }


def test_queue_batch_is_consumed_once_and_mutation_snapshot_stays_live() -> None:
    batch = _page(_state(), _state(pull_request_id="PR_kwDOsecond", number=13))
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(batch), ""),
            CommandResult(("gh",), 0, json.dumps({"data": {"node": _state()}}), ""),
        ]
    )
    queue = GitHubQueueGraphQLAdapter(repo=Path("/repo"), runner=runner)

    queue.prime_open_snapshots(repository_name="owner/repo")
    assert queue.observed_snapshot("PR_kwDOexample").head_sha == "b" * 40
    assert queue.observed_snapshot("PR_kwDOexample").head_sha == "b" * 40
    assert len(runner.calls) == 2
    assert "--paginate" in runner.calls[0]
    assert "DeliveryQueueState" in " ".join(runner.calls[1])


def test_adapter_reuses_open_pr_snapshot_once_then_refreshes() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh", "pr", "list"), 0, json.dumps([_node_payload()]), ""),
            CommandResult(
                ("gh", "repo", "view"),
                0,
                json.dumps({"nameWithOwner": "owner/repo"}),
                "",
            ),
            CommandResult(("gh", "graphql"), 0, json.dumps(_page(_state())), ""),
            CommandResult(
                ("gh", "pr", "view"),
                0,
                json.dumps(_node_payload(head="c" * 40)),
                "",
            ),
        ]
    )
    adapter = GitHubCliAdapter(repo=Path("/repo"), runner=runner)

    adapter.list_open_pull_requests()
    adapter.prime_open_observations()

    assert adapter.get_pull_request(12).head_sha == "b" * 40
    assert adapter.get_pull_request(12).head_sha == "c" * 40
    assert sum(1 for call in runner.calls if call[:3] == ("gh", "pr", "view")) == 1


def test_pr_mutation_bypasses_read_only_snapshot_cache() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh", "pr", "list"), 0, json.dumps([_node_payload()]), ""),
            CommandResult(
                ("gh", "pr", "view"),
                0,
                json.dumps(_node_payload(head="c" * 40)),
                "",
            ),
            CommandResult(("gh", "pr", "edit"), 0, "", ""),
            CommandResult(
                ("gh", "pr", "view"),
                0,
                json.dumps(_node_payload(head="c" * 40)),
                "",
            ),
        ]
    )
    adapter = GitHubCliAdapter(repo=Path("/repo"), runner=runner)

    adapter.list_open_pull_requests()
    updated = adapter.update_pull_request(
        number=12,
        title="fix: updated",
        body="updated body",
        expected_head_sha="c" * 40,
    )

    assert updated.head_sha == "c" * 40
    assert sum(1 for call in runner.calls if call[:3] == ("gh", "pr", "view")) == 2


def test_required_observations_are_primed_once_after_open_inventory() -> None:
    runner = StaticRunner(
        [CommandResult(("gh", "pr", "list"), 0, json.dumps([_node_payload()]), "")]
    )
    adapter = GitHubCliAdapter(repo=Path("/repo"), runner=runner)
    calls: list[tuple[int, ...]] = []
    sentinel = object()
    adapter._checks.prime_required_snapshots = lambda numbers: calls.append(numbers)
    adapter._checks.required_snapshot = lambda number: sentinel

    adapter.list_open_pull_requests()

    assert adapter.required_check_snapshot(12) is sentinel
    assert adapter.required_check_snapshot(12) is sentinel
    assert calls == [(12,)]


def test_malformed_queue_batch_falls_back_to_exact_live_snapshot() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps({"data": {"repository": None}}), ""),
            CommandResult(
                ("gh",), 0, json.dumps({"data": {"node": _state(entry_id="MQE_1")}}), ""
            ),
        ]
    )
    queue = GitHubQueueGraphQLAdapter(repo=Path("/repo"), runner=runner)

    queue.prime_open_snapshots(repository_name="owner/repo")

    assert queue.observed_snapshot("PR_kwDOexample").entry_id == "MQE_1"
    assert "DeliveryQueueState" in " ".join(runner.calls[1])
