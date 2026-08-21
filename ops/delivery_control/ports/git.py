from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.observations import PhysicalWorktree, WorktreeSnapshot


@runtime_checkable
class GitQueryPort(Protocol):
    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]: ...

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot: ...

    def remote_branch_sha(self, branch: str) -> str | None: ...

    def local_main_sha(self) -> str: ...

    def origin_main_sha(self) -> str: ...


@runtime_checkable
class GitCommandPort(Protocol):
    def push_branch(
        self,
        *,
        worktree: Path,
        branch: str,
        expected_local_sha: str,
        expected_remote_sha: str | None = None,
    ) -> str: ...

    def remove_worktree(self, path: Path, *, expected_head_sha: str) -> None: ...

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None: ...

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str: ...
