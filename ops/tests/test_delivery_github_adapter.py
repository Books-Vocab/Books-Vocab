from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.errors import AdapterCommandError
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.domain.errors import CompareAndSwapConflict
from delivery_control.domain.models import CheckStatus
from delivery_control.domain.observations import (
    InventoryProblem,
)
from delivery_control.ports.process import CommandResult


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0)


def _pr_payload() -> dict[str, object]:
    return {
        "id": "PR_kwDOexample",
        "number": 12,
        "url": "https://example.test/pull/12",
        "headRefName": "feat/one",
        "baseRefName": "main",
        "baseRefOid": "a" * 40,
        "headRefOid": "b" * 40,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "title": "fix: one",
        "body": "## Scope\n- ops/a.py\n\n## Validation\n- required",
        "autoMergeRequest": None,
    }


def test_github_adapter_surfaces_malformed_entries() -> None:
    runner = StaticRunner(
        [
            CommandResult(
                argv=("gh", "pr", "list"),
                exit_code=0,
                stdout=json.dumps([_pr_payload(), 7]),
                stderr="",
            )
        ]
    )
    inventory = GitHubCliAdapter(runner=runner).list_open_pull_requests()
    assert [item.number for item in inventory.records] == [12]
    assert inventory.problems == (
        InventoryProblem("github", "entry[1]", "PR entry is not an object"),
    )


def test_github_adapter_reads_terminal_prs_for_one_published_branch() -> None:
    merged = _pr_payload()
    merged["state"] = "MERGED"
    runner = StaticRunner([CommandResult(("gh",), 0, json.dumps([merged]), "")])

    inventory = GitHubCliAdapter(runner=runner).list_pull_requests_for_branch(
        "feat/one"
    )

    assert inventory.records[0].state == "MERGED"
    assert "--state" in runner.calls[0]
    assert "all" in runner.calls[0]
    assert "--head" in runner.calls[0]


def test_github_create_pr_explicitly_targets_main() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, "https://example.test/pull/12", ""),
            CommandResult(("gh",), 0, json.dumps([_pr_payload()]), ""),
        ]
    )

    created = GitHubCliAdapter(runner=runner).create_pull_request(
        branch="feat/one",
        title="fix: one",
        body="body",
    )

    assert created.number == 12
    create_call = runner.calls[0]
    assert create_call[0:3] == ("gh", "pr", "create")
    assert create_call[create_call.index("--base") + 1] == "main"


def test_github_required_check_snapshot_is_bound_to_exact_head() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(
                ("gh",),
                0,
                json.dumps([{"state": "SUCCESS", "name": "required"}]),
                "",
            ),
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
        ]
    )
    snapshot = GitHubCliAdapter(runner=runner).required_check_snapshot(12)
    assert snapshot.status is CheckStatus.SUCCESS
    assert snapshot.head_sha == "b" * 40
    assert snapshot.names == ("required",)


def test_github_merge_history_is_typed_and_sorted() -> None:
    runner = StaticRunner(
        [
            CommandResult(
                ("gh",),
                0,
                json.dumps(
                    [
                        {"mergedAt": "2026-08-21T00:05:00Z"},
                        {"mergedAt": "2026-08-21T00:00:00Z"},
                    ]
                ),
                "",
            )
        ]
    )

    observed = GitHubCliAdapter(runner=runner).recent_merge_times(limit=20)

    assert [item.minute for item in observed] == [0, 5]


def test_github_required_checks_preserve_empty_nonzero_command_failure() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(("gh",), 1, "", "network failure"),
        ]
    )

    with pytest.raises(AdapterCommandError):
        GitHubCliAdapter(runner=runner).required_check_snapshot(12)


def test_github_enqueue_delegates_to_native_queue_without_direct_merge() -> None:
    queue_state = {
        "data": {
            "node": {
                "id": "PR_kwDOexample",
                "baseRefName": "main",
                "baseRefOid": "a" * 40,
                "headRefOid": "b" * 40,
                "body": _pr_payload()["body"],
                "state": "OPEN",
                "mergeQueueEntry": None,
            }
        }
    }
    enqueued = {"data": {"enqueuePullRequest": {"mergeQueueEntry": {"id": "MQE_1"}}}}
    queued = json.loads(json.dumps(queue_state))
    queued["data"]["node"]["mergeQueueEntry"] = {"id": "MQE_1"}
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(("gh",), 0, json.dumps([{"type": "merge_queue"}]), ""),
            CommandResult(("gh",), 0, json.dumps(queue_state), ""),
            CommandResult(("gh",), 0, json.dumps(enqueued), ""),
            CommandResult(("gh",), 0, json.dumps(queued), ""),
        ]
    )
    adapter = GitHubCliAdapter(runner=runner)

    adapter.enqueue(
        number=12,
        expected_base_sha="a" * 40,
        expected_head_sha="b" * 40,
        expected_body=str(_pr_payload()["body"]),
    )

    assert all(call[:3] != ("gh", "pr", "merge") for call in runner.calls)
    enqueue_call = next(
        call for call in runner.calls if "enqueuePullRequest" in " ".join(call)
    )
    assert f"expectedHeadOid={'b' * 40}" in enqueue_call


def test_github_enqueue_refuses_branch_without_merge_queue_rule() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(
                ("gh",), 0, json.dumps([{"type": "required_status_checks"}]), ""
            ),
        ]
    )

    with pytest.raises(CompareAndSwapConflict, match="no native merge queue"):
        GitHubCliAdapter(runner=runner).enqueue(
            number=12,
            expected_base_sha="a" * 40,
            expected_head_sha="b" * 40,
            expected_body=str(_pr_payload()["body"]),
        )


def test_github_adapter_observes_native_queue_entry() -> None:
    queue_state = {
        "data": {
            "node": {
                "id": "PR_kwDOexample",
                "baseRefName": "main",
                "baseRefOid": "a" * 40,
                "headRefOid": "b" * 40,
                "body": "body",
                "state": "OPEN",
                "mergeQueueEntry": {"id": "MQE_1"},
            }
        }
    }
    runner = StaticRunner([CommandResult(("gh",), 0, json.dumps(queue_state), "")])

    entry_id = GitHubCliAdapter(runner=runner).merge_queue_entry_id("PR_kwDOexample")

    assert entry_id == "MQE_1"


def test_github_enqueue_rejects_body_drift_before_graphql_mutation() -> None:
    drifted = _pr_payload()
    drifted["body"] = "tampered"
    runner = StaticRunner([CommandResult(("gh",), 0, json.dumps(drifted), "")])

    with pytest.raises(CompareAndSwapConflict, match="before enqueue"):
        GitHubCliAdapter(runner=runner).enqueue(
            number=12,
            expected_base_sha="a" * 40,
            expected_head_sha="b" * 40,
            expected_body=str(_pr_payload()["body"]),
        )

    assert all("enqueuePullRequest" not in " ".join(call) for call in runner.calls)


def test_github_metadata_update_requires_expected_handback_head() -> None:
    payload = _pr_payload()
    payload["headRefOid"] = "c" * 40
    runner = StaticRunner([CommandResult(("gh",), 0, json.dumps(payload), "")])

    with pytest.raises(CompareAndSwapConflict, match="before metadata"):
        GitHubCliAdapter(runner=runner).update_pull_request(
            number=12,
            title="fix: exact",
            body="## Scope\nexact",
            expected_head_sha="b" * 40,
        )

    assert len(runner.calls) == 1
