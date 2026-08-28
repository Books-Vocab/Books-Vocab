"""Body-only repair for one already durable pull request."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import PullRequestSnapshot, RegistrySnapshot
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from ..ports.registry import RegistryPublishedClaimQueryPort, RegistryQueryPort
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


def _receipt_from_current_claim(
    previous: HandbackReceipt,
    record: RegistrySnapshot,
    pull_request: PullRequestSnapshot,
) -> HandbackReceipt:
    """Rebuild a receipt only across an exact, owner-preserving generation drift."""

    # The old PR body may carry a historical origin; the current registry seal
    # remains the authoritative, separately validated origin below.
    if (
        record.status not in {"published", "cleanup_pending"}
        or record.lane_id != previous.lane_id
        or record.branch != previous.branch
        or record.path.resolve() != Path(previous.worktree_path).resolve()
        or record.base_sha != previous.base_sha
        or record.owner_thread_id != previous.owner_thread_id
        or record.handed_back_sha != previous.head_sha
        or record.scope != previous.scope
        or record.handback_claim_generation != record.claim_generation
        or not record.handback_valid
        or record.handback_digest is None
        or record.handback_origin_main_sha is None
    ):
        raise PolicyViolation("current published claim differs from the old receipt")
    published_base = record.published_base_sha or record.base_sha
    if (
        pull_request.state != "OPEN"
        or pull_request.base_branch != "main"
        or pull_request.branch != record.branch
        or pull_request.head_sha != record.handed_back_sha
        or pull_request.base_sha != published_base
    ):
        raise PolicyViolation("PR does not match the current published claim")
    try:
        return HandbackReceipt(
            lane_id=record.lane_id,
            owner_thread_id=record.owner_thread_id,
            claim_generation=record.claim_generation,
            branch=record.branch,
            worktree_path=str(record.path),
            base_sha=record.base_sha,
            parent_sha=previous.parent_sha,
            head_sha=record.handed_back_sha,
            origin_main_sha=record.handback_origin_main_sha,
            content_digest=record.handback_digest,
            scope=record.scope,
            validation=record.handback_outcomes,
            initial_holds=record.handback_initial_holds,
        )
    except (TypeError, ValueError) as error:
        raise PolicyViolation(
            "current published claim handback is malformed"
        ) from error


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

    def _receipt_for_repair(
        self, pull_request: PullRequestSnapshot
    ) -> tuple[HandbackReceipt, str]:
        receipt = parse_pull_request_body(pull_request.body)
        try:
            exact_published_record(self.registry, receipt)
        except PolicyViolation:
            if not isinstance(self.registry, RegistryPublishedClaimQueryPort):
                raise
            current = self.registry.find_published_claim(
                lane_id=receipt.lane_id,
                branch=receipt.branch,
                path=Path(receipt.worktree_path),
                owner_thread_id=receipt.owner_thread_id,
                head_sha=receipt.head_sha,
                scope=receipt.scope,
            )
            if current is None:
                raise
            return (
                _receipt_from_current_claim(receipt, current, pull_request),
                current.published_base_sha or current.base_sha,
            )
        return receipt, receipt.base_sha

    def repair(self, number: int) -> MetadataRepairResult:
        before = self.query.get_pull_request(number)
        receipt, expected_base_sha = self._receipt_for_repair(before)
        if (
            before.state != "OPEN"
            or before.base_branch != "main"
            or before.branch != receipt.branch
            or before.head_sha != receipt.head_sha
            or (
                expected_base_sha != receipt.base_sha
                and before.base_sha != expected_base_sha
            )
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
