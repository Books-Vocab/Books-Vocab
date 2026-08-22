"""Stable GitHub CLI adapter facade composed from focused components."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.candidate_issues import CandidateIssue, CandidateIssueInventory
from ..domain.demand_issues import DemandIssue, DemandIssueInventory
from ..domain.observations import (
    CheckSnapshot,
    MergeQueueEntrySnapshot,
    PullRequestInventory,
    PullRequestSnapshot,
)
from ..ports.process import CommandRunnerPort
from .errors import AdapterPayloadError
from .github_checks import GitHubChecks
from .github_client import GitHubCliClient
from .github_commands import GitHubCommands
from .github_issue_commands import GitHubIssueCommands
from .github_issue_queries import GitHubIssueQueries
from .github_parsing import (
    parse_candidate_issue,
    parse_candidate_issue_inventory,
    parse_pull_request,
    parse_pull_request_inventory,
)
from .github_queries import PR_FIELDS, GitHubQueries
from .github_queue import GitHubQueueGraphQLAdapter
from .github_rules import GitHubRules, read_repository_name
from .subprocess_runner import SubprocessCommandRunner

_PR_FIELDS = PR_FIELDS


class GitHubCliAdapter:
    """Compatibility facade implementing the GitHub query and command ports."""

    def __init__(
        self,
        *,
        repo: Path | None = None,
        runner: CommandRunnerPort | None = None,
    ) -> None:
        self.repo = (repo or Path.cwd()).resolve()
        self.runner = runner or SubprocessCommandRunner()
        self.queue = GitHubQueueGraphQLAdapter(repo=self.repo, runner=self.runner)
        self._client = GitHubCliClient(repo=self.repo, runner=self.runner)
        self._rules = GitHubRules(
            client=self._client,
            repository_name=self._repo_name,
        )
        self._queries = GitHubQueries(
            client=self._client,
            repository_name=self._repo_name,
            pull_request_parser=self._pull_request,
            pull_request_inventory_parser=self._pull_request_inventory,
            candidate_inventory_parser=self._candidate_issue_inventory,
        )
        self._issue_queries = GitHubIssueQueries(
            repo=self.repo,
            runner=self.runner,
            repository_name=self._repo_name,
        )
        self._issue_commands = GitHubIssueCommands(
            repo=self.repo,
            runner=self.runner,
            client=self._client,
            query=self._issue_queries,
        )
        self._checks = GitHubChecks(
            client=self._client,
            get_pull_request=self.get_pull_request,
        )
        self._commands = GitHubCommands(
            client=self._client,
            queue=self.queue,
            find_open_pull_request=self.find_open_pull_request,
            get_pull_request=self.get_pull_request,
            merge_queue_enabled=self.merge_queue_enabled,
        )

    def _run(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> str:
        return self._client.run(argv, allow_nonzero=allow_nonzero)

    def _json(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> Any:
        return self._client.load_json(argv, allow_nonzero=allow_nonzero)

    @staticmethod
    def _pull_request(payload: Mapping[str, Any]) -> PullRequestSnapshot:
        return parse_pull_request(payload)

    @classmethod
    def _pull_request_inventory(cls, payload: object) -> PullRequestInventory:
        return parse_pull_request_inventory(payload, parse_record=cls._pull_request)

    @staticmethod
    def _candidate_issue(payload: Mapping[str, Any]) -> CandidateIssue:
        return parse_candidate_issue(payload)

    @classmethod
    def _candidate_issue_inventory(cls, payload: object) -> CandidateIssueInventory:
        return parse_candidate_issue_inventory(
            payload,
            parse_record=cls._candidate_issue,
        )

    def list_open_candidate_issues(self) -> CandidateIssueInventory:
        return self._queries.list_open_candidate_issues()

    def list_open_issues(self) -> DemandIssueInventory:
        return self._issue_queries.list_open_issues()

    def admit_candidate(self, **kwargs: Any) -> DemandIssue:
        return self._issue_commands.admit_candidate(**kwargs)

    def list_open_pull_requests(self) -> PullRequestInventory:
        return self._queries.list_open_pull_requests()

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return self._queries.list_pull_requests_for_branch(branch)

    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]:
        return self._queries.recent_merge_times(limit=limit)

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        inventory = self.list_open_pull_requests()
        if inventory.problems:
            raise AdapterPayloadError("GitHub PR inventory contains malformed entries")
        matches = [item for item in inventory.records if item.branch == branch]
        if len(matches) > 1:
            raise AdapterPayloadError(f"multiple open PRs found for {branch}")
        return matches[0] if matches else None

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        return self._queries.get_pull_request(number)

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        return self._checks.required_snapshot(number)

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return self._queries.changed_paths(number)

    def _repo_name(self) -> str:
        return read_repository_name(self._client)

    def branch_is_protected(self, branch: str) -> bool:
        return self._rules.branch_is_protected(branch)

    def required_status_contexts(self, branch: str) -> tuple[str, ...]:
        return self._rules.required_status_contexts(branch)

    def merge_queue_enabled(self, branch: str) -> bool:
        return self.queue.is_configured(
            repository_name=self._repo_name(),
            branch=branch,
        )

    def merge_queue_entry_id(self, pull_request_id: str) -> str | None:
        return self.queue.snapshot(pull_request_id).entry_id

    def merge_queue_entry_snapshot(self, pull_request_id: str) -> MergeQueueEntrySnapshot | None:
        return self.queue.snapshot(pull_request_id).entry

    def trigger_required(
        self,
        *,
        number: int,
        branch: str,
        base_sha: str,
        head_sha: str,
    ) -> tuple[str, ...]:
        return self._commands.trigger_required(
            number=number,
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
        )

    def trigger_readiness(
        self,
        *,
        number: int,
        branch: str,
        head_sha: str,
    ) -> tuple[str, ...]:
        return self._commands.trigger_readiness(
            number=number,
            branch=branch,
            head_sha=head_sha,
        )

    def create_pull_request(self, *, branch: str, title: str, body: str) -> PullRequestSnapshot:
        return self._commands.create_pull_request(branch=branch, title=title, body=body)

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        return self._commands.update_pull_request(
            number=number,
            title=title,
            body=body,
            expected_head_sha=expected_head_sha,
        )

    def mark_ready(self, number: int) -> PullRequestSnapshot:
        return self._commands.mark_ready(number)

    def close_pull_request(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> PullRequestSnapshot:
        return self._commands.close_pull_request(
            number=number,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        )

    def reopen_pull_request(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> PullRequestSnapshot:
        return self._commands.reopen_pull_request(
            number=number,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        )

    def enqueue(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> None:
        self._commands.enqueue(
            number=number,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        )
