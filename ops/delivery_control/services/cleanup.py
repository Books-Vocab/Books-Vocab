"""Idempotent local-asset release and terminal branch cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import PullRequestSnapshot, RegistrySnapshot
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryCommandPort, RegistryQueryPort
from .publish import render_pull_request_body


@dataclass(frozen=True)
class CleanupResult:
    disposition: str
    worktree_absent: bool
    local_branch_absent: bool
    remote_branch_absent: bool


class CleanupService:
    def __init__(
        self,
        *,
        registry_query: RegistryQueryPort,
        registry_command: RegistryCommandPort,
        git_query: GitQueryPort,
        git_command: GitCommandPort,
        github: GitHubQueryPort,
    ) -> None:
        self.registry_query = registry_query
        self.registry_command = registry_command
        self.git_query = git_query
        self.git_command = git_command
        self.github = github

    def _record(self, receipt: HandbackReceipt) -> RegistrySnapshot:
        inventory = self.registry_query.list_records()
        if inventory.problems:
            raise PolicyViolation("registry inventory is incomplete")
        matches = [
            record
            for record in inventory.records
            if record.lane_id == receipt.lane_id
            and record.branch == receipt.branch
            and record.path.resolve() == Path(receipt.worktree_path).resolve()
            and record.claim_generation == receipt.claim_generation
            and record.handed_back_sha == receipt.head_sha
            and record.status in {"active", "published", "merged"}
        ]
        if len(matches) != 1:
            raise PolicyViolation("local claim does not resolve to one exact handback")
        record = matches[0]
        if (
            record.base_sha != receipt.base_sha
            or record.scope != receipt.scope
            or record.owner_thread_id != receipt.owner_thread_id
            or not record.handback_valid
            or record.handback_digest != receipt.content_digest
            or record.handback_origin_main_sha != receipt.origin_main_sha
        ):
            raise PolicyViolation("local claim differs from typed handback")
        return record

    def _pull_request(
        self,
        receipt: HandbackReceipt,
        number: int,
        *,
        expected_state: str,
    ) -> PullRequestSnapshot:
        pull_request = self.github.get_pull_request(number)
        if (
            pull_request.state != expected_state
            or pull_request.branch != receipt.branch
            or pull_request.head_sha != receipt.head_sha
            or pull_request.body != render_pull_request_body(receipt)
            or tuple(sorted(self.github.changed_paths(number)))
            != tuple(sorted(receipt.scope.paths))
        ):
            raise PolicyViolation("PR does not prove the exact handback disposition")
        return pull_request

    def _remove_local_assets(self, receipt: HandbackReceipt) -> None:
        physical = tuple(
            item
            for item in self.git_query.list_worktrees()
            if item.branch == receipt.branch
        )
        if len(physical) > 1 or (
            physical
            and physical[0].path.resolve() != Path(receipt.worktree_path).resolve()
        ):
            raise PolicyViolation("branch is attached to an unexpected worktree")
        if physical:
            snapshot = self.git_query.inspect_worktree(
                physical[0].path, receipt.base_sha
            )
            if (
                not snapshot.clean
                or snapshot.head_sha != receipt.head_sha
                or snapshot.branch != receipt.branch
                or tuple(snapshot.changed_paths) != receipt.scope.paths
            ):
                raise PolicyViolation("worktree changed after typed handback")
            self.git_command.remove_worktree(
                physical[0].path, expected_head_sha=receipt.head_sha
            )
        local_sha = self.git_query.local_branch_sha(receipt.branch)
        if local_sha is not None:
            if local_sha != receipt.head_sha:
                raise PolicyViolation("local branch changed after typed handback")
            self.git_command.delete_local_branch(
                receipt.branch, expected_head_sha=receipt.head_sha
            )

    def release_after_publish(
        self, *, receipt: HandbackReceipt, pull_request_number: int
    ) -> CleanupResult:
        record = self._record(receipt)
        if record.status == "merged":
            raise PolicyViolation("merged lane requires terminal cleanup")
        self._pull_request(receipt, pull_request_number, expected_state="OPEN")
        if self.git_query.remote_branch_sha(receipt.branch) != receipt.head_sha:
            raise PolicyViolation("remote branch does not preserve published HEAD")
        self._validate_local_assets(receipt)
        if record.status == "active":
            self.registry_command.resolve(
                receipt.lane_id,
                "published",
                expected_claim_generation=receipt.claim_generation,
                expected_branch=receipt.branch,
                expected_path=receipt.worktree_path,
                expected_head_sha=receipt.head_sha,
            )
        self._remove_local_assets(receipt)
        return self._result(receipt, "published")

    def _validate_local_assets(self, receipt: HandbackReceipt) -> None:
        physical = tuple(
            item
            for item in self.git_query.list_worktrees()
            if item.branch == receipt.branch
        )
        if len(physical) > 1 or (
            physical
            and physical[0].path.resolve() != Path(receipt.worktree_path).resolve()
        ):
            raise PolicyViolation("branch is attached to an unexpected worktree")
        if physical:
            snapshot = self.git_query.inspect_worktree(
                physical[0].path, receipt.base_sha
            )
            if (
                not snapshot.clean
                or snapshot.head_sha != receipt.head_sha
                or snapshot.branch != receipt.branch
                or tuple(snapshot.changed_paths) != receipt.scope.paths
            ):
                raise PolicyViolation("worktree changed after typed handback")
        local_sha = self.git_query.local_branch_sha(receipt.branch)
        if local_sha is not None and local_sha != receipt.head_sha:
            raise PolicyViolation("local branch changed after typed handback")

    def finalize_merged(
        self, *, receipt: HandbackReceipt, pull_request_number: int
    ) -> CleanupResult:
        record = self._record(receipt)
        self._pull_request(receipt, pull_request_number, expected_state="MERGED")
        self._remove_local_assets(receipt)
        remote_sha = self.git_query.remote_branch_sha(receipt.branch)
        if remote_sha is not None:
            if remote_sha != receipt.head_sha:
                raise PolicyViolation("remote branch changed after merged HEAD")
            self.git_command.delete_remote_branch(
                receipt.branch, expected_head_sha=receipt.head_sha
            )
        if record.status != "merged":
            self.registry_command.resolve(
                receipt.lane_id,
                "merged",
                expected_claim_generation=receipt.claim_generation,
                expected_branch=receipt.branch,
                expected_path=receipt.worktree_path,
                expected_head_sha=receipt.head_sha,
            )
        return self._result(receipt, "merged")

    def _result(self, receipt: HandbackReceipt, disposition: str) -> CleanupResult:
        branch_worktrees = tuple(
            item
            for item in self.git_query.list_worktrees()
            if item.branch == receipt.branch
        )
        return CleanupResult(
            disposition=disposition,
            worktree_absent=not branch_worktrees,
            local_branch_absent=self.git_query.local_branch_sha(receipt.branch) is None,
            remote_branch_absent=self.git_query.remote_branch_sha(receipt.branch) is None,
        )
