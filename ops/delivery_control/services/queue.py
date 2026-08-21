"""Exact admission into GitHub's native merge queue."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import CheckSnapshot, PullRequestSnapshot, RegistrySnapshot
from ..domain.policies import evaluate_merge_gate
from ..domain.states import HoldKind
from ..ports.git import GitQueryPort
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from .publish import render_pull_request_body


@dataclass(frozen=True)
class QueueResult:
    pull_request: PullRequestSnapshot
    required: CheckSnapshot
    live_main_sha: str


class QueueService:
    def __init__(
        self,
        *,
        registry: RegistryQueryPort,
        git: GitQueryPort,
        github_query: GitHubQueryPort,
        github_command: GitHubCommandPort,
    ) -> None:
        self.registry = registry
        self.git = git
        self.github_query = github_query
        self.github_command = github_command

    def _record(self, receipt: HandbackReceipt) -> RegistrySnapshot:
        inventory = self.registry.list_records()
        if inventory.problems:
            raise PolicyViolation("registry inventory is incomplete")
        matches = [
            item
            for item in inventory.records
            if item.lane_id == receipt.lane_id
            and item.branch == receipt.branch
            and item.path.resolve() == Path(receipt.worktree_path).resolve()
            and item.status == "published"
            and item.base_sha == receipt.base_sha
            and item.scope == receipt.scope
            and item.claim_generation == receipt.claim_generation
            and item.owner_thread_id == receipt.owner_thread_id
            and item.handed_back_sha == receipt.head_sha
            and item.handback_claim_generation == receipt.claim_generation
            and item.handback_valid
            and item.handback_digest == receipt.content_digest
            and item.handback_origin_main_sha == receipt.origin_main_sha
        ]
        if len(matches) != 1:
            raise PolicyViolation("merge admission lacks one exact local receipt")
        return matches[0]

    def enqueue(
        self,
        *,
        receipt: HandbackReceipt,
        pull_request_number: int,
        holds: frozenset[HoldKind] = frozenset(),
    ) -> QueueResult:
        live_main_sha = self.git.origin_main_sha()
        record = self._record(receipt)
        if not self.github_query.merge_queue_enabled("main"):
            raise PolicyViolation("main does not require GitHub merge queue admission")
        pull_request = self.github_query.get_pull_request(pull_request_number)
        if pull_request.body != render_pull_request_body(receipt):
            raise PolicyViolation("PR body differs from typed handback")
        if tuple(sorted(self.github_query.changed_paths(pull_request_number))) != tuple(
            sorted(receipt.scope.paths)
        ):
            raise PolicyViolation("PR paths differ from typed Scope")
        required = self.github_query.required_check_snapshot(pull_request_number)
        decision = evaluate_merge_gate(
            pull_request=pull_request,
            receipt=receipt,
            live_main_sha=live_main_sha,
            registry=record,
            required=required,
            holds=holds,
        )
        if not decision.allowed:
            raise PolicyViolation("; ".join(decision.reasons))
        self.github_command.enqueue(
            number=pull_request_number,
            expected_base_sha=live_main_sha,
            expected_head_sha=receipt.head_sha,
        )
        return QueueResult(
            pull_request=pull_request,
            required=required,
            live_main_sha=live_main_sha,
        )
