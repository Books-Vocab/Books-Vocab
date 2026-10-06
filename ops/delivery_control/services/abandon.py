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
from .pr_contract import parse_pull_request_body, pull_request_holds


@dataclass(frozen=True)
class AbandonResult:
    pull_request_number: int
    pull_request_state: str
    registry_status: str
    remote_branch_absent: bool


@dataclass(frozen=True)
class ScopeMismatchEvidence:
    """Durable evidence for a published receipt wider than its observed diff."""

    kind: str
    declared_scope_paths: tuple[str, ...]
    actual_changed_paths: tuple[str, ...]
    scope_only_paths: tuple[str, ...]
    outside_scope_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypedAbandonResult(AbandonResult):
    """Typed abandonment result without changing legacy cleanup output."""

    verdict: str = "terminalized"
    malformed_published_lane: bool = False
    delivery_succeeded: bool = False
    mismatch_evidence: ScopeMismatchEvidence | None = None


@dataclass(frozen=True)
class _AbandonContext:
    receipt: HandbackReceipt
    pull_request: PullRequestSnapshot
    registry: RegistrySnapshot
    remote_sha: str | None
    mismatch_evidence: ScopeMismatchEvidence | None


class AbandonService:
    """Close one exact unqueued PR and terminalize only its published lane.

    A strict typed-Scope superset is terminalized only as an explicitly
    malformed non-delivery, with the observed mismatch retained in the result.
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

    def _require_canonical_main(self) -> None:
        """Protect PR and remote-branch mutation from an owner checkout."""

        checkout = self.git_query.canonical_checkout()
        if checkout.branch != "main":
            raise PolicyViolation(
                "canonical checkout must be on main before abandonment"
            )
        if not checkout.clean:
            raise PolicyViolation("canonical checkout is dirty before abandonment")

    def abandon(self, *, pull_request_number: int) -> TypedAbandonResult:
        self._require_canonical_main()
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
        closed_mismatch_evidence = self._validate_pr(
            closed,
            context.receipt,
            expected_state="CLOSED",
            pull_request_number=pull_request_number,
        )
        if closed_mismatch_evidence != context.mismatch_evidence:
            raise CompareAndSwapConflict(
                "PR Scope evidence changed after closing the PR"
            )

        try:
            closed_context = self._read_exact(pull_request_number)
            if (
                closed_context.pull_request.state != "CLOSED"
                or closed_context.registry.status != "published"
                or closed_context.remote_sha != context.receipt.head_sha
                or closed_context.mismatch_evidence != context.mismatch_evidence
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
                or terminal_context.mismatch_evidence != context.mismatch_evidence
            ):
                raise CompareAndSwapConflict(
                    "abandoned registry transition did not read back exactly"
                )
        except (DeliverySourceError, OSError) as error:
            terminal_context = self._read_terminal_if_committed(
                pull_request_number,
                context.receipt,
                expected_mismatch_evidence=context.mismatch_evidence,
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
            or listed.number != pull_request.number
            or listed.node_id != pull_request.node_id
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
        if pull_request_holds(pull_request):
            raise PolicyViolation("abandonment refuses a PR with an explicit hard hold")

        receipt = parse_pull_request_body(pull_request.body)
        mismatch_evidence = self._validate_pr(
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
            mismatch_evidence=mismatch_evidence,
        )

    def _validate_pr(
        self,
        pull_request: PullRequestSnapshot,
        receipt: HandbackReceipt,
        *,
        expected_state: str,
        pull_request_number: int,
    ) -> ScopeMismatchEvidence | None:
        if (
            pull_request.number != pull_request_number
            or pull_request.state != expected_state
            or pull_request.base_branch != "main"
            or pull_request.base_sha != receipt.base_sha
            or pull_request.branch != receipt.branch
            or pull_request.head_sha != receipt.head_sha
            or parse_pull_request_body(pull_request.body) != receipt
        ):
            raise PolicyViolation("PR differs from the exact typed receipt")
        changed_paths = tuple(self.github_query.changed_paths(pull_request_number))
        if not changed_paths:
            raise PolicyViolation("PR changed paths are empty")
        if len(changed_paths) != len(set(changed_paths)):
            raise PolicyViolation("PR changed paths contain duplicates")
        expected_paths = tuple(sorted(receipt.scope.paths))
        actual_paths = tuple(sorted(changed_paths))
        outside_scope_paths = tuple(
            sorted(set(actual_paths).difference(receipt.scope.paths))
        )
        if outside_scope_paths:
            raise PolicyViolation("PR changed paths fall outside typed Scope")
        if actual_paths == expected_paths:
            return None
        if not receipt.scope.allows_changed_paths(changed_paths):
            raise PolicyViolation("PR changed paths do not fit typed Scope")
        return ScopeMismatchEvidence(
            kind="scope-strict-superset",
            declared_scope_paths=expected_paths,
            actual_changed_paths=actual_paths,
            scope_only_paths=tuple(
                sorted(set(expected_paths).difference(actual_paths))
            ),
        )

    @staticmethod
    def _validate_registry(
        registry: RegistrySnapshot, receipt: HandbackReceipt
    ) -> None:
        if registry.status not in {"published", "abandoned"}:
            raise PolicyViolation("registry is not in a post-publication state")
        if (
            registry.lane_id != receipt.lane_id
            or registry.owner_thread_id != receipt.owner_thread_id
        ):
            raise PolicyViolation("registry lane or owner differs from typed PR owner")
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
        self,
        pull_request_number: int,
        receipt: HandbackReceipt,
        *,
        expected_mismatch_evidence: ScopeMismatchEvidence | None,
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
            and context.mismatch_evidence == expected_mismatch_evidence
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
                or current.mismatch_evidence != original.mismatch_evidence
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
            reopened_mismatch_evidence = self._validate_pr(
                reopened,
                original.receipt,
                expected_state="OPEN",
                pull_request_number=original.pull_request.number,
            )
            if reopened_mismatch_evidence != original.mismatch_evidence:
                raise CompareAndSwapConflict(
                    "PR Scope evidence changed during compensation"
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
            or final.mismatch_evidence != context.mismatch_evidence
        ):
            raise CompareAndSwapConflict(
                "abandoned PR terminal state did not read back exactly"
            )
        return TypedAbandonResult(
            pull_request_number=final.pull_request.number,
            pull_request_state=final.pull_request.state,
            registry_status=final.registry.status,
            remote_branch_absent=True,
            verdict=(
                "terminalized-malformed"
                if context.mismatch_evidence is not None
                else "terminalized"
            ),
            malformed_published_lane=context.mismatch_evidence is not None,
            mismatch_evidence=context.mismatch_evidence,
        )
