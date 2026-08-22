"""Body-only repair for one already durable pull request."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import PolicyViolation
from ..domain.observations import PullRequestSnapshot
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from .pr_contract import (
    parse_pull_request_body,
    pull_request_holds,
    render_pull_request_body,
)
from .receipt_registry import exact_published_record


@dataclass(frozen=True)
class MetadataRepairResult:
    changed: bool
    pull_request: PullRequestSnapshot


class MetadataRepairService:
    def __init__(
        self,
        *,
        registry: RegistryQueryPort,
        query: GitHubQueryPort,
        command: GitHubCommandPort,
    ) -> None:
        self.registry = registry
        self.query = query
        self.command = command

    def repair(self, number: int) -> MetadataRepairResult:
        before = self.query.get_pull_request(number)
        receipt = parse_pull_request_body(before.body)
        exact_published_record(self.registry, receipt)
        if (
            before.state != "OPEN"
            or before.base_branch != "main"
            or before.branch != receipt.branch
            or before.head_sha != receipt.head_sha
            or tuple(sorted(self.query.changed_paths(number)))
            != tuple(sorted(receipt.scope.paths))
        ):
            raise PolicyViolation("PR tuple differs from the durable receipt")
        expected_body = render_pull_request_body(
            receipt,
            holds=pull_request_holds(before),
        )
        changed = before.body != expected_body
        current = before
        if changed:
            current = self.command.update_pull_request(
                number=number,
                title=before.title,
                body=expected_body,
                expected_head_sha=receipt.head_sha,
            )
        if current.draft:
            current = self.command.mark_ready(number)
            changed = True
        after = self.query.get_pull_request(number)
        if (
            after.state != "OPEN"
            or after.draft
            or after.base_branch != "main"
            or after.branch != receipt.branch
            or after.head_sha != receipt.head_sha
            or after.title != before.title
            or after.body != expected_body
            or tuple(sorted(self.query.changed_paths(number)))
            != tuple(sorted(receipt.scope.paths))
        ):
            raise PolicyViolation("repaired PR metadata did not read back exactly")
        return MetadataRepairResult(changed=changed, pull_request=after)
