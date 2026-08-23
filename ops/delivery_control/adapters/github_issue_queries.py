"""Paginated raw GitHub Issue inventory, separate from candidate parsing."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..domain.demand_issues import DemandIssueInventory
from ..domain.errors import DeliverySourceError
from ..ports.process import CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError
from .github_parsing import parse_demand_issue_inventory

_OPEN_ISSUES_QUERY = """
query DeliveryOpenIssues(
  $owner: String!,
  $name: String!,
  $cursor: String
) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, states: OPEN, after: $cursor) {
      nodes {
        id
        number
        url
        title
        body
        updatedAt
        labels(first: 100) {
          nodes { name }
          pageInfo { hasNextPage }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
""".strip()


class GitHubIssueQueries:
    """Read all open Issues with a bounded, cursor-based GraphQL walk."""

    def __init__(
        self,
        *,
        repo: Path,
        runner: CommandRunnerPort,
        repository_name: Callable[[], str],
    ) -> None:
        self.repo = repo
        self.runner = runner
        self.repository_name = repository_name

    def _graphql(self, *, cursor: str | None) -> Mapping[str, Any]:
        owner, separator, name = self.repository_name().partition("/")
        if not separator or not owner or not name or "/" in name:
            raise AdapterPayloadError("GitHub repository name must be owner/name")
        argv = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={_OPEN_ISSUES_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"cursor={cursor if cursor is not None else 'null'}",
        ]
        result = self.runner.run(tuple(argv), cwd=self.repo)
        if result.exit_code != 0:
            raise AdapterCommandError(result)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError("GitHub GraphQL returned invalid JSON") from error
        if not isinstance(payload, Mapping) or payload.get("errors"):
            raise AdapterPayloadError("GitHub GraphQL response contains errors")
        return payload

    def list_open_issues(self) -> DemandIssueInventory:
        payloads: list[object] = []
        cursor: str | None = None
        seen_cursors: set[str | None] = {None}
        for _ in range(100):
            payload = self._graphql(cursor=cursor)
            data = payload.get("data")
            repository = data.get("repository") if isinstance(data, Mapping) else None
            connection = (
                repository.get("issues") if isinstance(repository, Mapping) else None
            )
            if not isinstance(connection, Mapping):
                raise AdapterPayloadError("GitHub open Issue connection is malformed")
            nodes = connection.get("nodes")
            page_info = connection.get("pageInfo")
            if not isinstance(nodes, list) or not isinstance(page_info, Mapping):
                raise AdapterPayloadError("GitHub open Issue page is malformed")
            for node in nodes:
                if not isinstance(node, Mapping):
                    # Keep malformed nodes addressable without inventing a
                    # GitHub Issue number that could collide with real data.
                    payloads.append(node)
                    continue
                labels = node.get("labels")
                if not isinstance(labels, Mapping):
                    raise AdapterPayloadError(
                        "GitHub Issue labels connection is malformed"
                    )
                label_nodes = labels.get("nodes")
                label_page_info = labels.get("pageInfo")
                if (
                    not isinstance(label_nodes, list)
                    or not isinstance(label_page_info, Mapping)
                    or type(label_page_info.get("hasNextPage")) is not bool
                ):
                    raise AdapterPayloadError(
                        "GitHub Issue labels pageInfo is malformed"
                    )
                if label_page_info["hasNextPage"]:
                    raise DeliverySourceError(
                        "GitHub Issue label inventory is incomplete"
                    )
                payloads.append(
                    {
                        "id": node.get("id"),
                        "number": node.get("number"),
                        "url": node.get("url"),
                        "title": node.get("title"),
                        "body": node.get("body"),
                        "updatedAt": node.get("updatedAt"),
                        "labels": label_nodes,
                    }
                )
            has_next = page_info.get("hasNextPage")
            end_cursor = page_info.get("endCursor")
            if type(has_next) is not bool:
                raise AdapterPayloadError("GitHub Issue pageInfo is malformed")
            if not has_next:
                return parse_demand_issue_inventory(payloads)
            if type(end_cursor) is not str or not end_cursor:
                raise AdapterPayloadError("GitHub Issue pagination cursor is missing")
            if end_cursor in seen_cursors:
                raise DeliverySourceError(
                    "GitHub open Issue pagination cursor repeated before completion"
                )
            seen_cursors.add(end_cursor)
            cursor = end_cursor
        raise DeliverySourceError("GitHub open Issue pagination exceeded 100 pages")
