"""GraphQL adapter for reversible native merge-queue admission."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.errors import CompareAndSwapConflict
from ..ports.process import CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError

_QUEUE_STATE_QUERY = """
query DeliveryQueueState($pullRequestId: ID!) {
  node(id: $pullRequestId) {
    ... on PullRequest {
      id
      baseRefName
      baseRefOid
      headRefOid
      body
      state
      mergeQueueEntry { id }
    }
  }
}
""".strip()

_ENQUEUE_MUTATION = """
mutation DeliveryEnqueue($pullRequestId: ID!, $expectedHeadOid: GitObjectID!) {
  enqueuePullRequest(input: {
    pullRequestId: $pullRequestId,
    expectedHeadOid: $expectedHeadOid
  }) {
    mergeQueueEntry { id }
  }
}
""".strip()

_DEQUEUE_MUTATION = """
mutation DeliveryDequeue($pullRequestId: ID!) {
  dequeuePullRequest(input: { id: $pullRequestId }) { clientMutationId }
}
""".strip()


@dataclass(frozen=True)
class NativeQueueSnapshot:
    pull_request_id: str
    base_branch: str
    base_sha: str
    head_sha: str
    body: str
    state: str
    entry_id: str | None


class GitHubQueueGraphQLAdapter:
    """Own only native merge-queue GraphQL reads and mutations."""

    def __init__(self, *, repo: Path, runner: CommandRunnerPort) -> None:
        self.repo = repo
        self.runner = runner

    def _graphql(self, query: str, *variables: tuple[str, str]) -> Mapping[str, Any]:
        argv = ["gh", "api", "graphql", "-f", f"query={query}"]
        for name, value in variables:
            argv.extend(("-F", f"{name}={value}"))
        command = tuple(argv)
        result = self.runner.run(command, cwd=self.repo)
        if result.exit_code != 0:
            raise AdapterCommandError(result)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError("GitHub GraphQL returned invalid JSON") from error
        if not isinstance(payload, Mapping) or payload.get("errors"):
            raise AdapterPayloadError("GitHub GraphQL response contains errors")
        return payload

    def snapshot(self, pull_request_id: str) -> NativeQueueSnapshot:
        payload = self._graphql(_QUEUE_STATE_QUERY, ("pullRequestId", pull_request_id))
        data = payload.get("data")
        node = data.get("node") if isinstance(data, Mapping) else None
        required = {
            "id": str,
            "baseRefName": str,
            "baseRefOid": str,
            "headRefOid": str,
            "body": str,
            "state": str,
        }
        if not isinstance(node, Mapping) or any(
            type(node.get(key)) is not expected for key, expected in required.items()
        ):
            raise AdapterPayloadError("GitHub merge-queue state is malformed")
        entry = node.get("mergeQueueEntry")
        if entry is not None and (
            not isinstance(entry, Mapping) or type(entry.get("id")) is not str
        ):
            raise AdapterPayloadError("GitHub merge-queue entry is malformed")
        return NativeQueueSnapshot(
            pull_request_id=node["id"],
            base_branch=node["baseRefName"],
            base_sha=node["baseRefOid"],
            head_sha=node["headRefOid"],
            body=node["body"],
            state=node["state"],
            entry_id=entry["id"] if isinstance(entry, Mapping) else None,
        )

    def _enqueue_mutation(self, pull_request_id: str, expected_head_sha: str) -> str:
        payload = self._graphql(
            _ENQUEUE_MUTATION,
            ("pullRequestId", pull_request_id),
            ("expectedHeadOid", expected_head_sha),
        )
        data = payload.get("data")
        result = data.get("enqueuePullRequest") if isinstance(data, Mapping) else None
        entry = result.get("mergeQueueEntry") if isinstance(result, Mapping) else None
        if not isinstance(entry, Mapping) or type(entry.get("id")) is not str:
            raise AdapterPayloadError("GitHub enqueue response is malformed")
        return entry["id"]

    def _dequeue(self, pull_request_id: str) -> None:
        payload = self._graphql(_DEQUEUE_MUTATION, ("pullRequestId", pull_request_id))
        data = payload.get("data")
        if not isinstance(data, Mapping) or not isinstance(
            data.get("dequeuePullRequest"), Mapping
        ):
            raise AdapterPayloadError("GitHub dequeue response is malformed")

    @staticmethod
    def _matches_preflight(
        snapshot: NativeQueueSnapshot,
        *,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> bool:
        return (
            snapshot.base_branch == "main"
            and snapshot.base_sha == expected_base_sha
            and snapshot.head_sha == expected_head_sha
            and snapshot.body == expected_body
            and snapshot.state == "OPEN"
        )

    def enqueue(
        self,
        *,
        pull_request_id: str,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> None:
        before = self.snapshot(pull_request_id)
        if not self._matches_preflight(
            before,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        ):
            raise CompareAndSwapConflict("PR tuple changed before native enqueue")
        if before.entry_id is not None:
            return

        entry_id = self._enqueue_mutation(pull_request_id, expected_head_sha)
        after = self.snapshot(pull_request_id)
        tuple_matches = (
            after.base_branch == "main"
            and after.head_sha == expected_head_sha
            and after.body == expected_body
        )
        queue_matches = after.state == "MERGED" or after.entry_id == entry_id
        if tuple_matches and queue_matches:
            return

        if after.entry_id == entry_id:
            self._dequeue(pull_request_id)
            rolled_back = self.snapshot(pull_request_id)
            if rolled_back.entry_id is not None:
                raise CompareAndSwapConflict(
                    "PR tuple changed and native queue rollback did not read back"
                )
        raise CompareAndSwapConflict("PR tuple changed during native enqueue")
