"""One-Issue candidate admission with read-before/write/readback safeguards."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from ..domain.candidate_issues import CANDIDATE_ISSUE_LABEL, CandidateSpec
from ..domain.demand_issues import (
    DemandIssue,
    IssueIntakeReceipt,
    IssueIntakeRequest,
    issue_body_sha256,
    issue_intake_fingerprint,
)
from ..domain.errors import (
    CompareAndSwapConflict,
    DeliverySourceError,
    PolicyViolation,
)
from ..ports.process import CommandRunnerPort
from ..services.candidate_contract import render_candidate_body
from .github_client import GitHubCliClient
from .errors import AdapterCommandError, AdapterPayloadError
from .github_issue_queries import GitHubIssueQueries
from .github_parsing import parse_demand_issue

_CREATE_ISSUE_REPOSITORY_QUERY = """
query DeliveryIssueRepository($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id
    labels(first: 100) {
      nodes { id name }
      pageInfo { hasNextPage endCursor }
    }
  }
}
""".strip()

_CREATE_ISSUE_MUTATION = """
mutation DeliveryCreateIssue(
  $repositoryId: ID!,
  $title: String!,
  $body: String!,
  $labelIds: [ID!],
  $clientMutationId: String!
) {
  createIssue(input: {
    repositoryId: $repositoryId,
    title: $title,
    body: $body,
    labelIds: $labelIds,
    clientMutationId: $clientMutationId
  }) {
    clientMutationId
    issue {
      id number url title body state updatedAt
      labels(first: 100) {
        nodes { name }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""".strip()

_READ_ISSUE_QUERY = """
query DeliveryReadIssue($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id number url title body state updatedAt
      labels(first: 100) {
        nodes { name }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""".strip()


class GitHubIssueCommands:
    """Mutate one explicitly admitted Issue; never bulk-migrates the backlog."""

    def __init__(
        self,
        *,
        repo: Path,
        runner: CommandRunnerPort,
        client: GitHubCliClient,
        query: GitHubIssueQueries,
    ) -> None:
        self.repo = repo
        self.runner = runner
        self.client = client
        self.query = query

    def _graphql(
        self,
        query: str,
        *,
        variables: tuple[tuple[str, str], ...] = (),
        list_variables: tuple[tuple[str, tuple[str, ...]], ...] = (),
    ) -> Mapping[str, Any]:
        owner, separator, name = self.query.repository_name().partition("/")
        if not separator or not owner or not name or "/" in name:
            raise AdapterPayloadError("GitHub repository name must be owner/name")
        argv = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
        ]
        for variable, value in variables:
            argv.extend(("-F", f"{variable}={value}"))
        for variable, values in list_variables:
            for value in values:
                argv.extend(("-F", f"{variable}[]={value}"))
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

    @staticmethod
    def _issue_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            raise AdapterPayloadError("GitHub created Issue payload is malformed")
        labels = payload.get("labels")
        if not isinstance(labels, Mapping):
            raise AdapterPayloadError("GitHub created Issue labels are malformed")
        label_nodes = labels.get("nodes")
        page_info = labels.get("pageInfo")
        if (
            not isinstance(label_nodes, list)
            or not isinstance(page_info, Mapping)
            or type(page_info.get("hasNextPage")) is not bool
        ):
            raise AdapterPayloadError("GitHub created Issue labels are malformed")
        if page_info["hasNextPage"]:
            raise DeliverySourceError(
                "GitHub created Issue label inventory is incomplete"
            )
        return {
            "id": payload.get("id"),
            "number": payload.get("number"),
            "url": payload.get("url"),
            "title": payload.get("title"),
            "body": payload.get("body"),
            "updatedAt": payload.get("updatedAt"),
            "labels": label_nodes,
        }

    def _repository_label_ids(
        self, request: IssueIntakeRequest
    ) -> tuple[str, tuple[str, ...]]:
        payload = self._graphql(_CREATE_ISSUE_REPOSITORY_QUERY)
        data = payload.get("data")
        repository = data.get("repository") if isinstance(data, Mapping) else None
        labels = repository.get("labels") if isinstance(repository, Mapping) else None
        if not isinstance(repository, Mapping) or type(repository.get("id")) is not str:
            raise AdapterPayloadError("GitHub repository identity is malformed")
        if not isinstance(labels, Mapping):
            raise AdapterPayloadError("GitHub repository label inventory is malformed")
        page_info = labels.get("pageInfo")
        nodes = labels.get("nodes")
        if (
            not isinstance(nodes, list)
            or not isinstance(page_info, Mapping)
            or type(page_info.get("hasNextPage")) is not bool
        ):
            raise AdapterPayloadError("GitHub repository label inventory is malformed")
        if page_info["hasNextPage"]:
            raise DeliverySourceError("GitHub repository label inventory is incomplete")
        by_name: dict[str, str] = {}
        for node in nodes:
            if (
                not isinstance(node, Mapping)
                or type(node.get("id")) is not str
                or type(node.get("name")) is not str
                or not node["id"]
                or not node["name"]
            ):
                raise AdapterPayloadError("GitHub repository label entry is malformed")
            by_name[node["name"]] = node["id"]
        missing = sorted(set(request.labels).difference(by_name))
        if missing:
            raise PolicyViolation(
                "GitHub repository is missing requested labels: " + ", ".join(missing)
            )
        return repository["id"], tuple(by_name[label] for label in request.labels)

    def _read_created_issue(self, number: int) -> DemandIssue:
        payload = self._graphql(
            _READ_ISSUE_QUERY,
            variables=(("number", str(number)),),
        )
        data = payload.get("data")
        repository = data.get("repository") if isinstance(data, Mapping) else None
        issue = repository.get("issue") if isinstance(repository, Mapping) else None
        if not isinstance(issue, Mapping) or issue.get("state") != "OPEN":
            raise AdapterPayloadError("GitHub created Issue readback is malformed")
        return parse_demand_issue(self._issue_payload(issue))

    def _issue(self, number: int) -> DemandIssue:
        inventory = self.query.list_open_issues()
        if not inventory.complete:
            raise DeliverySourceError(
                "cannot admit an Issue from an incomplete raw inventory"
            )
        matches = [item for item in inventory.records if item.number == number]
        if len(matches) != 1:
            raise PolicyViolation(f"open Issue #{number} is not uniquely readable")
        target_identity = f"Issue#{number}"
        if any(
            problem.identity == target_identity
            or problem.identity.startswith(f"{target_identity}@")
            for problem in inventory.problems
        ) or any(entry.issue_number == number for entry in inventory.source_entries):
            raise DeliverySourceError(
                f"cannot admit Issue #{number} while its raw source entry is malformed"
            )
        return matches[0]

    @staticmethod
    def _validate_operator_text(value: str, name: str) -> None:
        if (
            type(value) is not str
            or not value.strip()
            or any(
                character in "\r\n" or ord(character) < 32 or ord(character) == 127
                for character in value
            )
        ):
            raise PolicyViolation(f"Issue admission {name} must be one safe line")

    def _add_label(self, number: int) -> None:
        self.client.run(
            (
                "gh",
                "issue",
                "edit",
                str(number),
                "--add-label",
                CANDIDATE_ISSUE_LABEL,
            )
        )

    def _candidate_label_exists(self) -> bool:
        payload = self.client.load_json(
            (
                "gh",
                "label",
                "list",
                "--search",
                CANDIDATE_ISSUE_LABEL,
                "--limit",
                "100",
                "--json",
                "name",
            )
        )
        if not isinstance(payload, list):
            raise PolicyViolation("GitHub label inventory is malformed")
        return any(
            isinstance(item, dict) and item.get("name") == CANDIDATE_ISSUE_LABEL
            for item in payload
        )

    def admit_candidate(
        self,
        *,
        issue_number: int,
        expected_updated_at: datetime,
        expected_body_sha256: str,
        spec: CandidateSpec,
        triage_reason: str,
        operator: str,
    ) -> DemandIssue:
        self._validate_operator_text(triage_reason, "triage_reason")
        self._validate_operator_text(operator, "operator")
        current = self._issue(issue_number)
        if current.candidate_spec is not None:
            if current.candidate_spec != spec:
                raise CompareAndSwapConflict(
                    f"Issue #{issue_number} already contains a different candidate contract"
                )
            if CANDIDATE_ISSUE_LABEL not in current.labels:
                self._add_label(issue_number)
                final = self._issue(issue_number)
                if CANDIDATE_ISSUE_LABEL not in final.labels:
                    raise CompareAndSwapConflict(
                        f"Issue #{issue_number} label readback did not converge"
                    )
                return final
            return current
        if (
            current.updated_at != expected_updated_at
            or current.body_sha256 != expected_body_sha256
        ):
            raise CompareAndSwapConflict(
                f"Issue #{issue_number} changed after triage fingerprint"
            )
        if CANDIDATE_ISSUE_LABEL in current.labels:
            raise PolicyViolation(
                f"Issue #{issue_number} has candidate label without a valid contract"
            )
        if spec.initial_holds:
            raise PolicyViolation(
                "security/P0/P1 candidates cannot enter the dispatchable reservoir"
            )
        if not self._candidate_label_exists():
            raise PolicyViolation(
                f"GitHub label {CANDIDATE_ISSUE_LABEL!r} is not configured"
            )
        body = render_candidate_body(
            spec,
            original_body=current.body,
            triage_reason=triage_reason,
            operator=operator,
        )
        self.client.run(
            (
                "gh",
                "issue",
                "edit",
                str(issue_number),
                "--body",
                body,
            )
        )
        after_body = self._issue(issue_number)
        if (
            after_body.body != body
            or issue_body_sha256(after_body.body) != issue_body_sha256(body)
            or after_body.candidate_spec != spec
        ):
            raise CompareAndSwapConflict(
                f"Issue #{issue_number} body admission did not read back exactly"
            )
        self._add_label(issue_number)
        final = self._issue(issue_number)
        if (
            CANDIDATE_ISSUE_LABEL not in final.labels
            or final.candidate_spec != spec
            or final.body != body
        ):
            raise CompareAndSwapConflict(
                f"Issue #{issue_number} candidate admission did not converge"
            )
        return final

    def create_issue(self, *, request: IssueIntakeRequest) -> IssueIntakeReceipt:
        """Create one raw Issue exactly once, then verify its complete readback."""

        body = request.render_body()
        repository_id, label_ids = self._repository_label_ids(request)
        payload = self._graphql(
            _CREATE_ISSUE_MUTATION,
            variables=(
                ("repositoryId", repository_id),
                ("title", request.title),
                ("body", body),
                ("clientMutationId", request.client_mutation_id),
            ),
            list_variables=(("labelIds", label_ids),),
        )
        data = payload.get("data")
        mutation = data.get("createIssue") if isinstance(data, Mapping) else None
        if not isinstance(mutation, Mapping):
            raise AdapterPayloadError("GitHub createIssue response is malformed")
        if mutation.get("clientMutationId") != request.client_mutation_id:
            raise CompareAndSwapConflict(
                "GitHub createIssue clientMutationId readback did not match"
            )
        created = mutation.get("issue")
        created_payload = self._issue_payload(created)
        if type(created_payload.get("number")) is not int:
            raise AdapterPayloadError("GitHub created Issue number is malformed")

        final = self._read_created_issue(created_payload["number"])
        if (
            final.title != request.title
            or final.body != body
            or final.labels != request.labels
            or issue_body_sha256(final.body) != issue_body_sha256(body)
            or issue_intake_fingerprint(final.body) != request.source_fingerprint
        ):
            raise CompareAndSwapConflict(
                "GitHub created Issue did not read back exactly"
            )
        return IssueIntakeReceipt(
            issue=final,
            source_fingerprint=request.source_fingerprint,
            client_mutation_id=request.client_mutation_id,
        )
