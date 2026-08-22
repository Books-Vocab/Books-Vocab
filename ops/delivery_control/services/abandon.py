"""Exact post-publication PR abandonment transaction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import CompareAndSwapConflict, DeliverySourceError, PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import PullRequestSnapshot, RegistrySnapshot
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from ..ports.registry import RegistryCleanupQueryPort, RegistryCommandPort
from .pr_contract import parse_pull_request_body


@dataclass(frozen=True)
class AbandonResult:
    pull_request_number: int
    pull_request_state: str
    registry_status: str
    remote_branch_absent: bool


@dataclass(frozen=True)
class _AbandonContext:
    receipt: HandbackReceipt
    pull_request: PullRequestSnapshot
    registry: RegistrySnapshot
    remote_sha: str | None


class AbandonService:
    """Close one exact unqueued PR and terminalize only its published lane."""

    def __init__(
        self,
        *,
        registry_query: RegistryCleanupQueryPort,
        registry_command: RegistryCommandPort,
        git_query: GitQueryPort,
        git_command: GitCommandPort,
        github_query: GitHubQueryPort,
        github_command: GitHubCommandPort,
    ) -> None:
        self.registry_query = registry_query
        self.registry_command = registry_command
        self.git_query = git_query
        self.git_command = git_command
        self.github_query = github_query
        self.github_command = github_command

    def abandon(self, *, pull_request_number: int) -> AbandonResult:
        context = self._read_exact(pull_request_number)
        if context.registry.status == "abandoned":
            if context.pull_request.state != "CLOSED":
                raise PolicyViolation(
                    "abandoned registry recovery requires the exact CLOSED PR"
                )
            return self._finish_remote_cleanup(context)
        if context.registry.status != "published":
            raise PolicyViolation(
                "PR abandonment requires one published registry handback"
            )
        if context.pull_request.state != "OPEN":
            raise PolicyViolation("initial PR abandonment requires an OPEN PR")
        if context.remote_sha != context.receipt.head_sha:
            raise PolicyViolation("remote branch does not preserve the exact PR HEAD")

        closed = self.github_command.close_pull_request(
            number=pull_request_number,
            expected_base_sha=context.pull_request.base_sha,
            expected_head_sha=context.receipt.head_sha,
            expected_body=context.pull_request.body,
        )
        self._validate_pr(
            closed,
            context.receipt,
            expected_state="CLOSED",
            pull_request_number=pull_request_number,
        )

        try:
            closed_context = self._read_exact(pull_request_number)
            if (
                closed_context.pull_request.state != "CLOSED"
                or closed_context.registry.status != "published"
                or closed_context.remote_sha != context.receipt.head_sha
            ):
                raise CompareAndSwapConflict(
                    "abandonment tuple changed after closing the PR"
                )
            self.registry_command.resolve(
                context.receipt.lane_id,
                "abandoned",
                expected_claim_generation=context.receipt.claim_generation,
                expected_branch=context.receipt.branch,
                expected_path=context.receipt.worktree_path,
                expected_head_sha=context.receipt.head_sha,
            )
            terminal_context = self._read_exact(pull_request_number)
            if (
                terminal_context.pull_request.state != "CLOSED"
                or terminal_context.registry.status != "abandoned"
                or terminal_context.remote_sha != context.receipt.head_sha
            ):
                raise CompareAndSwapConflict(
                    "abandoned registry transition did not read back exactly"
                )
        except (DeliverySourceError, OSError) as error:
            terminal_context = self._read_terminal_if_committed(
                pull_request_number, context.receipt
            )
            if terminal_context is None:
                self._reopen_after_uncommitted_failure(context, error)
                raise

        return self._finish_remote_cleanup(terminal_context)

    def _read_exact(self, pull_request_number: int) -> _AbandonContext:
        pull_request = self.github_query.get_pull_request(pull_request_number)
        inventory = self.github_query.list_pull_requests_for_branch(pull_request.branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        if (
            len(inventory.records) != 1
            or inventory.records[0].number != pull_request_number
        ):
            raise PolicyViolation("branch does not map to one unique PR")
        listed = inventory.records[0]
        if (
            listed.branch != pull_request.branch
            or listed.base_branch != pull_request.base_branch
            or listed.base_sha != pull_request.base_sha
            or listed.head_sha != pull_request.head_sha
            or listed.state != pull_request.state
            or listed.body != pull_request.body
            or listed.merged_at != pull_request.merged_at
        ):
            raise CompareAndSwapConflict(
                "GitHub PR changed between exact branch and number readbacks"
            )
        if pull_request.merged_at is not None or pull_request.state == "MERGED":
            raise PolicyViolation("merged PR cannot be abandoned")
        if not pull_request.node_id:
            raise PolicyViolation("PR lacks an exact GitHub node identity")
        if (
            pull_request.auto_merge_enabled
            or self.github_query.merge_queue_entry_snapshot(pull_request.node_id)
            is not None
        ):
            raise PolicyViolation("PR is already scheduled in the merge queue")

        receipt = parse_pull_request_body(pull_request.body)
        self._validate_pr(
            pull_request,
            receipt,
            expected_state=pull_request.state,
            pull_request_number=pull_request_number,
        )
        registry = self.registry_query.find_exact_claim(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=Path(receipt.worktree_path),
            claim_generation=receipt.claim_generation,
        )
        if registry is None:
            raise PolicyViolation("typed receipt has no exact registry claim")
        self._validate_registry(registry, receipt)
        self._validate_local_assets_absent(receipt)
        return _AbandonContext(
            receipt=receipt,
            pull_request=pull_request,
            registry=registry,
            remote_sha=self.git_query.remote_branch_sha(receipt.branch),
        )

    def _validate_pr(
        self,
        pull_request: PullRequestSnapshot,
        receipt: HandbackReceipt,
        *,
        expected_state: str,
        pull_request_number: int,
    ) -> None:
        if (
            pull_request.number != pull_request_number
            or pull_request.state != expected_state
            or pull_request.base_branch != "main"
            or pull_request.base_sha != receipt.base_sha
            or pull_request.branch != receipt.branch
            or pull_request.head_sha != receipt.head_sha
            or parse_pull_request_body(pull_request.body) != receipt
            or tuple(sorted(self.github_query.changed_paths(pull_request_number)))
            != tuple(sorted(receipt.scope.paths))
        ):
            raise PolicyViolation("PR differs from the exact typed receipt")

    @staticmethod
    def _validate_registry(
        registry: RegistrySnapshot, receipt: HandbackReceipt
    ) -> None:
        if registry.status not in {"published", "abandoned"}:
            raise PolicyViolation("registry is not in a post-publication state")
        if registry.owner_thread_id != receipt.owner_thread_id:
            raise PolicyViolation("registry owner differs from typed PR owner")
        if (
            registry.branch != receipt.branch
            or registry.path.resolve() != Path(receipt.worktree_path).resolve()
            or registry.base_sha != receipt.base_sha
            or registry.scope != receipt.scope
            or registry.handed_back_sha != receipt.head_sha
            or registry.handback_claim_generation != receipt.claim_generation
            or not registry.handback_valid
            or registry.handback_digest != receipt.content_digest
            or registry.handback_origin_main_sha != receipt.origin_main_sha
        ):
            raise PolicyViolation("registry differs from the exact typed receipt")

    def _validate_local_assets_absent(self, receipt: HandbackReceipt) -> None:
        path = Path(receipt.worktree_path).resolve()
        if self.git_query.local_branch_sha(receipt.branch) is not None or any(
            item.path.resolve() == path or item.branch == receipt.branch
            for item in self.git_query.list_worktrees()
        ):
            raise PolicyViolation(
                "post-publication abandonment requires local assets to be absent"
            )

    def _read_terminal_if_committed(
        self, pull_request_number: int, receipt: HandbackReceipt
    ) -> _AbandonContext | None:
        try:
            context = self._read_exact(pull_request_number)
        except (DeliverySourceError, OSError):
            return None
        if (
            context.receipt == receipt
            and context.pull_request.state == "CLOSED"
            and context.registry.status == "abandoned"
            and context.remote_sha == receipt.head_sha
        ):
            return context
        return None

    def _reopen_after_uncommitted_failure(
        self, original: _AbandonContext, cause: BaseException
    ) -> None:
        try:
            current = self._read_exact(original.pull_request.number)
            if (
                current.receipt != original.receipt
                or current.pull_request.state != "CLOSED"
                or current.registry.status != "published"
                or current.remote_sha != original.receipt.head_sha
            ):
                raise CompareAndSwapConflict(
                    "closed PR tuple is no longer safe to compensate"
                )
            reopened = self.github_command.reopen_pull_request(
                number=original.pull_request.number,
                expected_base_sha=original.pull_request.base_sha,
                expected_head_sha=original.receipt.head_sha,
                expected_body=original.pull_request.body,
            )
            self._validate_pr(
                reopened,
                original.receipt,
                expected_state="OPEN",
                pull_request_number=original.pull_request.number,
            )
        except (DeliverySourceError, OSError) as compensation_error:
            raise CompareAndSwapConflict(
                f"abandonment failed ({cause}); exact PR reopen compensation failed: "
                f"{compensation_error}"
            ) from cause

    def _finish_remote_cleanup(self, context: _AbandonContext) -> AbandonResult:
        if (
            context.pull_request.state != "CLOSED"
            or context.registry.status != "abandoned"
        ):
            raise PolicyViolation("remote cleanup requires exact abandoned PR proof")
        if context.remote_sha is not None:
            if context.remote_sha != context.receipt.head_sha:
                raise PolicyViolation("remote branch changed after PR abandonment")
            self.git_command.delete_remote_branch(
                context.receipt.branch,
                expected_head_sha=context.receipt.head_sha,
            )
        final = self._read_exact(context.pull_request.number)
        if (
            final.receipt != context.receipt
            or final.pull_request.state != "CLOSED"
            or final.registry.status != "abandoned"
            or final.remote_sha is not None
        ):
            raise CompareAndSwapConflict(
                "abandoned PR terminal state did not read back exactly"
            )
        return AbandonResult(
            pull_request_number=final.pull_request.number,
            pull_request_state=final.pull_request.state,
            registry_status=final.registry.status,
            remote_branch_absent=True,
        )
