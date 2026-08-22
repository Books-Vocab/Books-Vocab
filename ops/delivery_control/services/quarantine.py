"""Quarantine one malformed published PR without touching valid delivery lanes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import CompareAndSwapConflict, DeliverySourceError, PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import PullRequestSnapshot, RegistrySnapshot
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from ..ports.registry import RegistryCleanupQueryPort, RegistryCommandPort
from .pr_contract import parse_pull_request_body, pull_request_holds


@dataclass(frozen=True)
class QuarantineResult:
    pull_request_number: int
    pull_request_state: str
    registry_status: str
    remote_branch_absent: bool
    mismatches: tuple[str, ...]


@dataclass(frozen=True)
class _QuarantineContext:
    pull_request: PullRequestSnapshot
    receipt: HandbackReceipt
    registry: RegistrySnapshot
    remote_sha: str
    mismatches: tuple[str, ...]


class QuarantineService:
    """Close and release only a provably malformed published PR.

    This is intentionally narrower than normal abandonment: the typed receipt
    and registry claim must still agree with each other, while the durable PR
    tuple must disagree with that receipt in an explicit, reproducible way.
    """

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

    def quarantine(self, *, pull_request_number: int) -> QuarantineResult:
        context = self._read_exact(pull_request_number)
        closed = self.github_command.close_pull_request(
            number=context.pull_request.number,
            expected_base_sha=context.pull_request.base_sha,
            expected_head_sha=context.pull_request.head_sha,
            expected_body=context.pull_request.body,
        )
        self._validate_closed(closed, context)

        try:
            self.registry_command.resolve(
                context.receipt.lane_id,
                "abandoned",
                expected_claim_generation=context.receipt.claim_generation,
                expected_branch=context.receipt.branch,
                expected_path=context.receipt.worktree_path,
                expected_head_sha=context.receipt.head_sha,
            )
        except (DeliverySourceError, OSError) as error:
            self._reopen(context, error)
            raise

        terminal = self.registry_query.find_exact_claim(
            lane_id=context.receipt.lane_id,
            branch=context.receipt.branch,
            path=Path(context.receipt.worktree_path),
            claim_generation=context.receipt.claim_generation,
        )
        if terminal is None or terminal.status != "abandoned":
            raise CompareAndSwapConflict(
                "quarantine registry transition did not read back as abandoned"
            )
        remote_sha = self.git_query.remote_branch_sha(context.receipt.branch)
        if remote_sha != context.remote_sha:
            raise CompareAndSwapConflict(
                "remote branch changed after malformed PR quarantine"
            )
        self.git_command.delete_remote_branch(
            context.receipt.branch,
            expected_head_sha=context.remote_sha,
        )
        final = self._read_final(context)
        return QuarantineResult(
            pull_request_number=final.pull_request.number,
            pull_request_state=final.pull_request.state,
            registry_status=final.registry.status,
            remote_branch_absent=True,
            mismatches=context.mismatches,
        )

    def _read_exact(self, pull_request_number: int) -> _QuarantineContext:
        pull_request = self.github_query.get_pull_request(pull_request_number)
        inventory = self.github_query.list_pull_requests_for_branch(pull_request.branch)
        if inventory.problems or len(inventory.records) != 1:
            raise PolicyViolation("quarantine requires one exact PR for the branch")
        listed = inventory.records[0]
        if listed != pull_request:
            raise CompareAndSwapConflict("PR changed between exact branch readbacks")
        if (
            pull_request.state != "OPEN"
            or pull_request.base_branch != "main"
            or pull_request.merged_at is not None
        ):
            raise PolicyViolation("quarantine requires one open, unmerged PR on main")
        if pull_request.auto_merge_enabled or not pull_request.node_id:
            raise PolicyViolation("quarantine refuses an auto-merge or unidentified PR")
        if self.github_query.merge_queue_entry_snapshot(pull_request.node_id) is not None:
            raise PolicyViolation("quarantine refuses a PR already in the merge queue")
        if pull_request_holds(pull_request):
            raise PolicyViolation("quarantine refuses a PR with an explicit hard hold")

        receipt = parse_pull_request_body(pull_request.body)
        if receipt.branch != pull_request.branch or receipt.head_sha != pull_request.head_sha:
            raise PolicyViolation("quarantine requires a receipt matching branch and HEAD")
        registry = self.registry_query.find_exact_claim(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=Path(receipt.worktree_path),
            claim_generation=receipt.claim_generation,
        )
        if registry is None or registry.status not in {"published", "cleanup_pending"}:
            raise PolicyViolation("quarantine requires one published registry claim")
        self._validate_registry(registry, receipt)
        self._validate_local_assets_absent(receipt)
        remote_sha = self.git_query.remote_branch_sha(receipt.branch)
        if remote_sha != receipt.head_sha:
            raise PolicyViolation("quarantine requires an exact remote PR HEAD")

        mismatches: list[str] = []
        if pull_request.base_sha != receipt.base_sha:
            mismatches.append("pr-base-differs-from-receipt")
        actual_paths = tuple(sorted(self.github_query.changed_paths(pull_request_number)))
        expected_paths = tuple(sorted(receipt.scope.paths))
        if actual_paths != expected_paths:
            mismatches.append("pr-scope-differs-from-receipt")
        if not mismatches:
            raise PolicyViolation("exact typed PR must use the normal abandonment route")
        return _QuarantineContext(
            pull_request=pull_request,
            receipt=receipt,
            registry=registry,
            remote_sha=remote_sha,
            mismatches=tuple(mismatches),
        )

    @staticmethod
    def _validate_registry(
        registry: RegistrySnapshot, receipt: HandbackReceipt
    ) -> None:
        if (
            registry.owner_thread_id != receipt.owner_thread_id
            or registry.branch != receipt.branch
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
        target = Path(receipt.worktree_path).resolve()
        if self.git_query.local_branch_sha(receipt.branch) is not None or any(
            item.branch == receipt.branch or item.path.resolve() == target
            for item in self.git_query.list_worktrees()
        ):
            raise PolicyViolation("quarantine requires local assets to be absent")

    @staticmethod
    def _validate_closed(
        pull_request: PullRequestSnapshot, context: _QuarantineContext
    ) -> None:
        if (
            pull_request.state != "CLOSED"
            or pull_request.base_sha != context.pull_request.base_sha
            or pull_request.head_sha != context.pull_request.head_sha
            or pull_request.body != context.pull_request.body
        ):
            raise CompareAndSwapConflict("PR did not read back as the exact closed tuple")

    def _reopen(self, context: _QuarantineContext, cause: BaseException) -> None:
        try:
            current = self.github_query.get_pull_request(context.pull_request.number)
            if (
                current.state != "CLOSED"
                or current.base_sha != context.pull_request.base_sha
                or current.head_sha != context.pull_request.head_sha
                or current.body != context.pull_request.body
            ):
                raise CompareAndSwapConflict("closed PR tuple changed during compensation")
            reopened = self.github_command.reopen_pull_request(
                number=context.pull_request.number,
                expected_base_sha=context.pull_request.base_sha,
                expected_head_sha=context.pull_request.head_sha,
                expected_body=context.pull_request.body,
            )
            if reopened.state != "OPEN":
                raise CompareAndSwapConflict("quarantine compensation did not reopen PR")
        except (DeliverySourceError, OSError) as error:
            raise CompareAndSwapConflict(
                f"quarantine failed ({cause}); exact PR reopen compensation failed: {error}"
            ) from cause

    def _read_final(self, context: _QuarantineContext) -> _QuarantineContext:
        final_pr = self.github_query.get_pull_request(context.pull_request.number)
        if final_pr.state != "CLOSED":
            raise CompareAndSwapConflict("quarantine final PR state is not CLOSED")
        final_registry = self.registry_query.find_exact_claim(
            lane_id=context.receipt.lane_id,
            branch=context.receipt.branch,
            path=Path(context.receipt.worktree_path),
            claim_generation=context.receipt.claim_generation,
        )
        if final_registry is None or final_registry.status != "abandoned":
            raise CompareAndSwapConflict("quarantine final registry state is not abandoned")
        if self.git_query.remote_branch_sha(context.receipt.branch) is not None:
            raise CompareAndSwapConflict("quarantine remote branch was not deleted")
        return _QuarantineContext(
            pull_request=final_pr,
            receipt=context.receipt,
            registry=final_registry,
            remote_sha=context.remote_sha,
            mismatches=context.mismatches,
        )
