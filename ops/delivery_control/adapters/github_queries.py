"""Read-only GitHub CLI queries for Issues, pull requests, and changed files."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from ..domain.candidate_issues import CANDIDATE_ISSUE_LABEL, CandidateIssueInventory
from ..domain.errors import DeliverySourceError
from ..domain.observations import PullRequestInventory, PullRequestSnapshot
from .errors import AdapterPayloadError
from .github_client import GitHubCliClient
from .github_file_paths import parse_open_pull_request_file_pages
from .github_parsing import (
    parse_candidate_issue_inventory,
    parse_changed_paths,
    parse_merge_times,
    parse_pull_request,
    parse_pull_request_inventory,
)

PR_FIELDS = (
    "id,number,url,headRefName,baseRefName,baseRefOid,headRefOid,state,isDraft,mergeable,title,body,"
    "autoMergeRequest,labels,createdAt,mergedAt"
)

OPEN_PR_FILES_QUERY = """
query DeliveryOpenPullRequestFiles($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 100, states: OPEN, after: $endCursor) {
      nodes {
        number
        files(first: 100) {
          nodes { path changeType }
          pageInfo { hasNextPage endCursor }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
""".strip()


class GitHubQueries:
    def __init__(
        self,
        *,
        client: GitHubCliClient,
        repository_name: Callable[[], str],
        pull_request_parser: Callable[
            [Mapping[str, Any]], PullRequestSnapshot
        ] = parse_pull_request,
        pull_request_inventory_parser: Callable[
            [object], PullRequestInventory
        ] = parse_pull_request_inventory,
        candidate_inventory_parser: Callable[
            [object], CandidateIssueInventory
        ] = parse_candidate_issue_inventory,
    ) -> None:
        self.client = client
        self.repository_name = repository_name
        self.pull_request_parser = pull_request_parser
        self.pull_request_inventory_parser = pull_request_inventory_parser
        self.candidate_inventory_parser = candidate_inventory_parser
        self._known_open_pr_numbers: frozenset[int] = frozenset()
        self._open_file_batch_attempted = False
        self._changed_paths_cache: dict[int, tuple[str, ...]] = {}

    def list_open_candidate_issues(self) -> CandidateIssueInventory:
        payload = self.client.load_json(
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
        )
        return self.candidate_inventory_parser(payload)

    def list_open_pull_requests(self) -> PullRequestInventory:
        payload = self.client.load_json(
            (
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                PR_FIELDS,
            )
        )
        inventory = self.pull_request_inventory_parser(payload)
        self._known_open_pr_numbers = frozenset(
            item.number for item in inventory.records
        )
        self._open_file_batch_attempted = False
        self._changed_paths_cache = {}
        return inventory

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        payload = self.client.load_json(
            (
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--head",
                branch,
                "--limit",
                "100",
                "--json",
                PR_FIELDS,
            )
        )
        return self.pull_request_inventory_parser(payload)

    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("merge history limit must be between 1 and 100")
        payload = self.client.load_json(
            (
                "gh",
                "pr",
                "list",
                "--state",
                "merged",
                "--limit",
                str(limit),
                "--json",
                "mergedAt",
            )
        )
        return parse_merge_times(payload)

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        payload = self.client.load_json(
            ("gh", "pr", "view", str(number), "--json", PR_FIELDS)
        )
        if not isinstance(payload, Mapping):
            raise AdapterPayloadError("GitHub PR view must be a JSON object")
        return self.pull_request_parser(payload)

    def changed_paths(self, number: int) -> tuple[str, ...]:
        if (
            not self._open_file_batch_attempted
            and number in self._known_open_pr_numbers
        ):
            self._prime_open_pr_file_paths()
        cached = self._changed_paths_cache.get(number)
        if cached is not None:
            return cached
        payload = self.client.load_json(
            (
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repository_name()}/pulls/{number}/files",
            )
        )
        return parse_changed_paths(payload)

    def _prime_open_pr_file_paths(self) -> None:
        self._open_file_batch_attempted = True
        try:
            repository_name = self.repository_name()
            owner, separator, name = repository_name.partition("/")
            if not separator or not owner or not name or "/" in name:
                raise AdapterPayloadError("GitHub repository name must be owner/name")
            payload = self.client.load_json(
                (
                    "gh",
                    "api",
                    "graphql",
                    "--paginate",
                    "--slurp",
                    "-f",
                    f"query={OPEN_PR_FILES_QUERY}",
                    "-F",
                    f"owner={owner}",
                    "-F",
                    f"name={name}",
                )
            )
            batch = parse_open_pull_request_file_pages(payload)
        except DeliverySourceError:
            return
        self._changed_paths_cache.update(batch.paths_by_number)
