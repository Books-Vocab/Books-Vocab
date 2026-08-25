from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters import github_commands, github_parsing
from delivery_control.adapters.errors import AdapterCommandError, AdapterPayloadError
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.adapters.github_client import GitHubCliClient
from delivery_control.domain.candidate_issues import CANDIDATE_ISSUE_LABEL
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
        self.cwds: list[Path | None] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        self.cwds.append(cwd)
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


def _graphql_pr_node(payload: dict[str, object]) -> dict[str, object]:
    return {
        **payload,
        "labels": {
            "nodes": [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }


def _candidate_payload(number: int) -> dict[str, object]:
    return {
        "number": number,
        "url": f"https://github.com/owner/repo/issues/{number}",
        "state": "OPEN",
        "labels": [{"name": CANDIDATE_ISSUE_LABEL}],
        "body": (
            "<!-- kg.delivery.candidate.v1\n"
            + json.dumps(
                {
                    "schema": "kg.delivery.candidate.v1",
                    "severity": "P2",
                    "priority": number,
                    "scope": {
                        "schema": "kg.worktree.scope.v1",
                        "files": [
                            {
                                "operation": "modify",
                                "path": f"ops/issue_{number}.py",
                            }
                        ],
                    },
                    "acceptance": [f"Issue {number} is fixed."],
                    "initial_holds": [],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n-->"
        ),
    }


def _queue_configuration_payload(*, configured: bool) -> dict[str, object]:
    return {
        "data": {
            "repository": {
                "mergeQueue": (
                    {"configuration": {"mergingStrategy": "ALLGREEN"}}
                    if configured
                    else None
                )
            }
        }
    }


def test_github_json_query_retries_transient_failure_once() -> None:
    repo = Path("/tmp/kg-github-retry")
    argv = ("gh", "repo", "view", "--json", "nameWithOwner")
    runner = StaticRunner(
        [
            CommandResult(argv, 1, "", "TLS handshake timeout"),
            CommandResult(argv, 0, '{"nameWithOwner":"owner/repo"}', ""),
        ]
    )

    payload = GitHubCliClient(repo=repo, runner=runner).load_json(argv)

    assert payload == {"nameWithOwner": "owner/repo"}
    assert runner.calls == [argv, argv]
    assert runner.cwds == [repo, repo]


def test_github_json_query_retries_timed_out_result_once() -> None:
    argv = ("gh", "repo", "view", "--json", "nameWithOwner")
    runner = StaticRunner(
        [
            CommandResult(argv, 1, "", "", timed_out=True),
            CommandResult(argv, 0, '{"nameWithOwner":"owner/repo"}', ""),
        ]
    )

    payload = GitHubCliClient(
        repo=Path("/tmp/kg-github-retry"), runner=runner
    ).load_json(argv)

    assert payload == {"nameWithOwner": "owner/repo"}
    assert runner.calls == [argv, argv]


def test_github_json_query_retry_exhaustion_preserves_command_failure() -> None:
    repo = Path("/tmp/kg-github-retry")
    argv = ("gh", "repo", "view", "--json", "nameWithOwner")
    first = CommandResult(argv, 1, "", "connection reset by peer")
    second = CommandResult(argv, 1, "", "connection refused")
    runner = StaticRunner([first, second])

    with pytest.raises(AdapterCommandError) as error:
        GitHubCliClient(repo=repo, runner=runner).load_json(argv)

    assert error.value.result is second
    assert runner.calls == [argv, argv]
    assert runner.cwds == [repo, repo]


def test_github_json_query_does_not_retry_permanent_failure() -> None:
    argv = ("gh", "repo", "view", "--json", "nameWithOwner")
    runner = StaticRunner(
        [
            CommandResult(argv, 1, "", "HTTP 403: permission denied"),
            CommandResult(argv, 0, '{"nameWithOwner":"owner/repo"}', ""),
        ]
    )

    with pytest.raises(AdapterCommandError):
        GitHubCliClient(repo=Path("/tmp/kg-github-retry"), runner=runner).load_json(
            argv
        )

    assert runner.calls == [argv]


def test_github_json_query_does_not_retry_malformed_json() -> None:
    argv = ("gh", "repo", "view", "--json", "nameWithOwner")
    runner = StaticRunner(
        [
            CommandResult(argv, 0, "not-json", ""),
            CommandResult(argv, 0, '{"nameWithOwner":"owner/repo"}', ""),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="invalid JSON"):
        GitHubCliClient(repo=Path("/tmp/kg-github-retry"), runner=runner).load_json(
            argv
        )

    assert runner.calls == [argv]


def test_github_mutation_does_not_retry_transient_failure() -> None:
    argv = ("gh", "workflow", "run", "pr-gate.yml")
    runner = StaticRunner(
        [
            CommandResult(argv, 1, "", "temporary network failure"),
            CommandResult(argv, 0, "", ""),
        ]
    )

    with pytest.raises(AdapterCommandError):
        GitHubCliClient(repo=Path("/tmp/kg-github-retry"), runner=runner).run(argv)

    assert runner.calls == [argv]


def test_github_graphql_mutation_does_not_retry_transient_failure() -> None:
    argv = (
        "gh",
        "api",
        "graphql",
        "-f",
        "query=mutation DeliveryCreateIssue { createIssue { issue { number } } }",
    )
    runner = StaticRunner(
        [
            CommandResult(argv, 1, "", "connection reset by peer"),
            CommandResult(argv, 0, '{"data":{}}', ""),
        ]
    )

    with pytest.raises(AdapterCommandError):
        GitHubCliClient(repo=Path("/tmp/kg-github-retry"), runner=runner).load_json(
            argv
        )

    assert runner.calls == [argv]


@pytest.mark.parametrize(
    ("parser", "message"),
    (
        (
            github_parsing.parse_pull_request,
            "GitHub PR payload must be an object",
        ),
        (
            github_parsing.parse_candidate_issue,
            "GitHub candidate Issue payload must be an object",
        ),
        (
            github_parsing.parse_demand_issue,
            "GitHub raw Issue payload must be an object",
        ),
    ),
    ids=("pull-request", "candidate-issue", "demand-issue"),
)
@pytest.mark.parametrize("payload", (None, [], "not-an-object"))
def test_direct_github_parsers_reject_non_objects(
    parser, message: str, payload: object
) -> None:
    with pytest.raises(AdapterPayloadError, match=message):
        parser(payload)


def test_demand_issue_inventory_preserves_non_object_problems() -> None:
    inventory = github_parsing.parse_demand_issue_inventory([None, [], "not-an-object"])

    assert inventory.records == ()
    assert inventory.raw_count == 3
    assert [problem.identity for problem in inventory.problems] == [
        "entry[0]",
        "entry[1]",
        "entry[2]",
    ]
    assert [problem.reason for problem in inventory.problems] == [
        "raw Issue entry is not an object",
        "raw Issue entry is not an object",
        "raw Issue entry is not an object",
    ]


def test_github_adapter_reads_open_exact_label_candidate_issues() -> None:
    wrong_label = _candidate_payload(22)
    wrong_label["labels"] = [{"name": "delivery:candidates"}]
    missing_contract = _candidate_payload(23)
    missing_contract["body"] = "No typed contract"
    runner = StaticRunner(
        [
            CommandResult(
                argv=("gh", "issue", "list"),
                exit_code=0,
                stdout=json.dumps(
                    [_candidate_payload(21), wrong_label, missing_contract, 7]
                ),
                stderr="",
            )
        ]
    )

    inventory = GitHubCliAdapter(runner=runner).list_open_candidate_issues()

    assert [item.number for item in inventory.records] == [21]
    assert inventory.records[0].spec.priority == 21
    assert [item.identity for item in inventory.problems] == [
        "Issue#22",
        "Issue#23",
        "entry[3]",
    ]
    assert "typed candidate contract" in inventory.problems[1].reason
    assert runner.calls == [
        (
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            CANDIDATE_ISSUE_LABEL,
            "--limit",
            "1000",
            "--json",
            "number,url,state,labels,body",
        )
    ]


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


def test_github_adapter_reads_branch_history_with_one_snapshot() -> None:
    second = _pr_payload()
    second["number"] = 13
    second["headRefName"] = "feat/two"
    page = {
        "data": {
            "repository": {
                "branch0": {
                    "nodes": [_graphql_pr_node(_pr_payload())],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
                "branch1": {
                    "nodes": [_graphql_pr_node(second)],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }
        }
    }
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(("gh",), 0, json.dumps(page), ""),
        ]
    )

    inventory = GitHubCliAdapter(runner=runner).list_pull_requests_for_branches(
        ("feat/one", "feat/two")
    )

    assert [item.number for item in inventory.records] == [12, 13]
    assert len(runner.calls) == 2
    assert runner.calls[1][:3] == ("gh", "api", "graphql")
    query_argument = next(item for item in runner.calls[1] if item.startswith("query="))
    assert "DeliveryPullRequestHistoryByBranch" in query_argument
    assert "headRefName: $branch0" in query_argument
    assert "--paginate" not in runner.calls[1]


@pytest.mark.parametrize(
    ("page_info", "message"),
    (
        ({"hasNextPage": True, "endCursor": "cursor"}, "pagination is incomplete"),
        ({"hasNextPage": "yes", "endCursor": None}, "pageInfo is malformed"),
    ),
)
def test_github_adapter_fails_closed_on_history_page_contract(
    page_info: dict[str, object], message: str
) -> None:
    page = {
        "data": {
            "repository": {
                "branch0": {
                    "nodes": [],
                    "pageInfo": page_info,
                }
            }
        }
    }
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(("gh",), 0, json.dumps(page), ""),
        ]
    )

    with pytest.raises(AdapterPayloadError, match=message):
        GitHubCliAdapter(runner=runner).list_pull_requests_for_branches(("feat/one",))


def test_github_changed_paths_preserve_rename_source_and_destination() -> None:
    runner = StaticRunner(
        [
            CommandResult(
                ("gh",),
                0,
                json.dumps({"nameWithOwner": "owner/repo"}),
                "",
            ),
            CommandResult(
                ("gh",),
                0,
                json.dumps(
                    [
                        [
                            {
                                "filename": "ops/new.py",
                                "previous_filename": "ops/old.py",
                                "status": "renamed",
                            },
                            {"filename": "ops/added.py", "status": "added"},
                        ]
                    ]
                ),
                "",
            ),
        ]
    )

    paths = GitHubCliAdapter(runner=runner).changed_paths(12)

    assert paths == ("ops/added.py", "ops/new.py", "ops/old.py")
    assert runner.calls[1][:4] == ("gh", "api", "--paginate", "--slurp")


def test_github_changed_paths_reject_rename_without_previous_filename() -> None:
    runner = StaticRunner(
        [
            CommandResult(
                ("gh",),
                0,
                json.dumps({"nameWithOwner": "owner/repo"}),
                "",
            ),
            CommandResult(
                ("gh",),
                0,
                json.dumps([[{"filename": "ops/new.py", "status": "renamed"}]]),
                "",
            ),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="previous_filename"):
        GitHubCliAdapter(runner=runner).changed_paths(12)


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


def test_github_adapter_parses_pr_labels_and_required_timing_window() -> None:
    pull_request = _pr_payload()
    pull_request.update(
        {
            "labels": [{"name": "delivery-hold:security"}],
            "createdAt": "2026-08-21T00:00:00Z",
            "mergedAt": None,
        }
    )
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(pull_request), ""),
            CommandResult(
                ("gh",),
                0,
                json.dumps(
                    [
                        {
                            "state": "SUCCESS",
                            "name": "readiness",
                            "startedAt": "2026-08-21T00:00:10Z",
                            "completedAt": "2026-08-21T00:00:20Z",
                        },
                        {
                            "state": "SUCCESS",
                            "name": "required",
                            "startedAt": "2026-08-21T00:00:15Z",
                            "completedAt": "2026-08-21T00:00:45Z",
                        },
                    ]
                ),
                "",
            ),
            CommandResult(("gh",), 0, json.dumps(pull_request), ""),
        ]
    )

    snapshot = GitHubCliAdapter(runner=runner).required_check_snapshot(12)

    assert snapshot.started_at is not None and snapshot.started_at.second == 10
    assert snapshot.completed_at is not None and snapshot.completed_at.second == 45
    assert snapshot.duration_seconds == 35.0
    assert GitHubCliAdapter._pull_request(pull_request).labels == (
        "delivery-hold:security",
    )


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


def test_github_adapter_reads_unique_required_status_contexts() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(
                ("gh",),
                0,
                json.dumps(
                    {
                        "required_status_checks": {
                            "contexts": ["required"],
                            "checks": [
                                {"context": "required", "app_id": 15368},
                                {
                                    "context": "validate PR readiness contract",
                                    "app_id": 15368,
                                },
                            ],
                        }
                    }
                ),
                "",
            ),
            CommandResult(
                ("gh",),
                0,
                json.dumps(
                    [
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "required_status_checks": [
                                    {"context": "ruleset-required"}
                                ]
                            },
                        },
                        {"type": "merge_queue", "parameters": {}},
                    ]
                ),
                "",
            ),
        ]
    )

    contexts = GitHubCliAdapter(runner=runner).required_status_contexts("main")

    assert contexts == (
        "required",
        "ruleset-required",
        "validate PR readiness contract",
    )


def test_github_adapter_rejects_malformed_effective_required_status_contexts() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(("gh",), 0, json.dumps({"required_status_checks": None}), ""),
            CommandResult(
                ("gh",),
                0,
                json.dumps(
                    [
                        {
                            "type": "required_status_checks",
                            "parameters": {"required_status_checks": [7]},
                        }
                    ]
                ),
                "",
            ),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="required contexts"):
        GitHubCliAdapter(runner=runner).required_status_contexts("main")


def test_github_adapter_rejects_malformed_required_status_contexts() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(
                ("gh",),
                0,
                json.dumps({"required_status_checks": {"contexts": [7]}}),
                "",
            ),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="required contexts"):
        GitHubCliAdapter(runner=runner).required_status_contexts("main")


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
    queued["data"]["node"]["mergeQueueEntry"] = {
        "id": "MQE_1",
        "enqueuedAt": "2026-08-21T12:00:00Z",
    }
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(("gh",), 0, json.dumps({"nameWithOwner": "owner/repo"}), ""),
            CommandResult(
                ("gh",),
                0,
                json.dumps(_queue_configuration_payload(configured=True)),
                "",
            ),
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
                ("gh",),
                0,
                json.dumps(_queue_configuration_payload(configured=False)),
                "",
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
                "mergeQueueEntry": {
                    "id": "MQE_1",
                    "enqueuedAt": "2026-08-21T12:00:00Z",
                },
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


def test_github_metadata_update_requires_expected_handback_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _pr_payload()
    payload["headRefOid"] = "c" * 40
    monkeypatch.setattr(github_commands.time, "sleep", lambda _: None)
    runner = StaticRunner([CommandResult(("gh",), 0, json.dumps(payload), "")] * 5)

    with pytest.raises(CompareAndSwapConflict, match="before metadata"):
        GitHubCliAdapter(runner=runner).update_pull_request(
            number=12,
            title="fix: exact",
            body="## Scope\nexact",
            expected_head_sha="b" * 40,
        )

    assert len(runner.calls) == 5


def test_github_metadata_update_waits_for_eventual_head_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _pr_payload()
    stale["headRefOid"] = "c" * 40
    before = _pr_payload()
    after = _pr_payload()
    after["body"] = "updated body"
    monkeypatch.setattr(github_commands.time, "sleep", lambda _: None)
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(stale), ""),
            CommandResult(("gh",), 0, json.dumps(before), ""),
            CommandResult(("gh",), 0, "", ""),
            CommandResult(("gh",), 0, json.dumps(after), ""),
        ]
    )

    result = GitHubCliAdapter(runner=runner).update_pull_request(
        number=12,
        title="fix: exact",
        body="updated body",
        expected_head_sha="b" * 40,
    )

    assert result.body == "updated body"
    assert runner.calls[2][:3] == ("gh", "pr", "edit")


def test_github_metadata_update_fails_closed_after_post_write_head_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    after_drift = _pr_payload()
    after_drift["headRefOid"] = "d" * 40
    monkeypatch.setattr(github_commands.time, "sleep", lambda _: None)
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(("gh",), 0, "", ""),
            *[CommandResult(("gh",), 0, json.dumps(after_drift), "")] * 5,
        ]
    )

    with pytest.raises(CompareAndSwapConflict, match="during metadata"):
        GitHubCliAdapter(runner=runner).update_pull_request(
            number=12,
            title="fix: exact",
            body="updated body",
            expected_head_sha="b" * 40,
        )


@pytest.mark.parametrize(
    ("command", "before_state", "after_state"),
    (("close", "OPEN", "CLOSED"), ("reopen", "CLOSED", "OPEN")),
)
def test_github_pr_state_mutation_has_exact_tuple_cas_and_readback(
    command: str, before_state: str, after_state: str
) -> None:
    before = _pr_payload()
    before["state"] = before_state
    after = _pr_payload()
    after["state"] = after_state
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(before), ""),
            CommandResult(("gh",), 0, "", ""),
            CommandResult(("gh",), 0, json.dumps(after), ""),
        ]
    )
    adapter = GitHubCliAdapter(runner=runner)
    method = getattr(adapter, f"{command}_pull_request")

    result = method(
        number=12,
        expected_base_sha="a" * 40,
        expected_head_sha="b" * 40,
        expected_body=str(before["body"]),
    )

    assert result.state == after_state
    assert runner.calls[1] == ("gh", "pr", command, "12")


def test_github_close_rejects_tuple_drift_before_mutation() -> None:
    drifted = _pr_payload()
    drifted["headRefOid"] = "d" * 40
    runner = StaticRunner([CommandResult(("gh",), 0, json.dumps(drifted), "")])

    with pytest.raises(CompareAndSwapConflict, match="before close"):
        GitHubCliAdapter(runner=runner).close_pull_request(
            number=12,
            expected_base_sha="a" * 40,
            expected_head_sha="b" * 40,
            expected_body=str(drifted["body"]),
        )

    assert len(runner.calls) == 1


def test_github_adapter_dispatches_required_workflow_with_exact_pr_tuple() -> None:
    runner = StaticRunner([CommandResult(("gh",), 0, "", "")])
    adapter = GitHubCliAdapter(runner=runner)

    command = adapter.trigger_required(
        number=12,
        branch="feat/one",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )

    assert command == (
        "gh",
        "workflow",
        "run",
        "pr-gate.yml",
        "--ref",
        "feat/one",
        "-f",
        "pr_number=12",
        "-f",
        f"base_sha={'a' * 40}",
        "-f",
        f"head_sha={'b' * 40}",
    )
    assert runner.calls == [command]


def test_github_adapter_dispatches_readiness_after_exact_metadata_publish() -> None:
    runner = StaticRunner([CommandResult(("gh",), 0, "", "")])
    adapter = GitHubCliAdapter(runner=runner)

    command = adapter.trigger_readiness(
        number=12,
        branch="feat/one",
        head_sha="b" * 40,
    )

    assert command == (
        "gh",
        "workflow",
        "run",
        "pr-readiness.yml",
        "--ref",
        "feat/one",
        "-f",
        "pr_number=12",
        "-f",
        f"head_sha={'b' * 40}",
    )
    assert runner.calls == [command]


def test_github_adapter_reports_required_workflow_dispatch_failure() -> None:
    argv = (
        "gh",
        "workflow",
        "run",
        "pr-gate.yml",
        "--ref",
        "feat/one",
        "-f",
        "pr_number=12",
        "-f",
        f"base_sha={'a' * 40}",
        "-f",
        f"head_sha={'b' * 40}",
    )
    runner = StaticRunner([CommandResult(argv, 1, "", "workflow dispatch rejected")])

    with pytest.raises(
        AdapterCommandError,
        match=r"gh workflow run pr-gate\.yml.*workflow dispatch rejected",
    ):
        GitHubCliAdapter(runner=runner).trigger_required(
            number=12,
            branch="feat/one",
            base_sha="a" * 40,
            head_sha="b" * 40,
        )
