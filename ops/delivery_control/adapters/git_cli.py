"""Stable Git CLI adapter facade composed from focused components."""

from __future__ import annotations

from pathlib import Path

from ..domain.branch_refs import BranchInventory
from ..domain.observations import (
    CanonicalCheckoutSnapshot,
    FileChange,
    MainLandingSnapshot,
    PhysicalWorktree,
    WorktreeSnapshot,
)
from ..ports.process import CommandRunnerPort
from .git_client import GitCliClient
from .git_commands import GitCommands
from .git_parsing import parse_changed_files
from .git_queries import GitQueries
from .subprocess_runner import SubprocessCommandRunner


class GitCliAdapter:
    """Compatibility facade implementing the Git query and command ports."""

    def __init__(
        self,
        *,
        repo: Path,
        runner: CommandRunnerPort | None = None,
    ) -> None:
        self.repo = repo.resolve()
        self.runner = runner or SubprocessCommandRunner()
        self._client = GitCliClient(repo=self.repo, runner=self.runner)
        self._queries = GitQueries(client=self._client)
        self._commands = GitCommands(
            repo=self.repo,
            client=self._client,
            query=self,
        )

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        return self._client.run(*args, cwd=cwd)

    @staticmethod
    def _parse_changed_files(payload: str) -> tuple[FileChange, ...]:
        return parse_changed_files(payload)

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return self._queries.canonical_checkout()

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self._queries.list_worktrees()

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        return self._queries.inspect_worktree(path, base_sha)

    def branch_inventory(self) -> BranchInventory:
        return self._queries.branch_inventory()

    def remote_branch_sha(self, branch: str) -> str | None:
        return self._queries.remote_branch_sha(branch)

    def local_branch_sha(self, branch: str) -> str | None:
        return self._queries.local_branch_sha(branch)

    def local_main_sha(self) -> str:
        return self._queries.local_main_sha()

    def origin_main_sha(self) -> str:
        return self._queries.origin_main_sha()

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        return self._queries.is_ancestor(ancestor_sha, descendant_sha)

    def first_parent_landings(
        self, *, before_sha: str, after_sha: str
    ) -> tuple[MainLandingSnapshot, ...]:
        return self._queries.first_parent_landings(
            before_sha=before_sha, after_sha=after_sha
        )

    def push_branch(
        self,
        *,
        worktree: Path,
        branch: str,
        expected_local_sha: str,
        expected_remote_sha: str | None = None,
    ) -> str:
        return self._commands.push_branch(
            worktree=worktree,
            branch=branch,
            expected_local_sha=expected_local_sha,
            expected_remote_sha=expected_remote_sha,
        )

    def remove_worktree(self, path: Path, *, expected_head_sha: str) -> None:
        self._commands.remove_worktree(path, expected_head_sha=expected_head_sha)

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        self._commands.delete_local_branch(
            branch,
            expected_head_sha=expected_head_sha,
        )

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        self._commands.delete_remote_branch(
            branch,
            expected_head_sha=expected_head_sha,
        )

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        return self._commands.fast_forward_main(
            expected_local_sha=expected_local_sha,
            expected_origin_sha=expected_origin_sha,
        )
