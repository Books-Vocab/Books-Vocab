from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.branch_content import (
    BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT,
    BranchContentEvidence,
)
from ..domain.branch_refs import BranchInventory
from ..domain.observations import (
    CanonicalCheckoutSnapshot,
    MainLandingSnapshot,
    PhysicalWorktree,
    WorktreeSnapshot,
)
from ..domain.unreachable_commits import UnreachableCommitInventory


@runtime_checkable
class GitQueryPort(Protocol):
    def canonical_checkout(self) -> CanonicalCheckoutSnapshot: ...

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]: ...

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot: ...

    def branch_inventory(self) -> BranchInventory: ...

    def unreachable_commit_inventory(self) -> UnreachableCommitInventory: ...

    def remote_branch_sha(self, branch: str) -> str | None: ...

    def local_branch_sha(self, branch: str) -> str | None: ...

    def local_main_sha(self) -> str: ...

    def origin_main_sha(self) -> str: ...

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool: ...


@runtime_checkable
class GitDiffFingerprintPort(Protocol):
    """Optional exact content-fingerprint capability for branch reconciliation."""

    def diff_fingerprint(self, base_sha: str, head_sha: str) -> str: ...


class BranchContentQueryPort(Protocol):
    """Read-only content evidence for a local branch review packet."""

    def inspect_branch_content(
        self,
        *,
        branch: str,
        base_sha: str,
        max_commit_summaries: int = BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT,
    ) -> BranchContentEvidence: ...

    def first_parent_landings(
        self, *, before_sha: str, after_sha: str
    ) -> tuple[MainLandingSnapshot, ...]: ...


class UnreachableCommitQueryPort(Protocol):
    """Optional read-only capability for one unreachable commit object."""

    def inspect_unreachable_commit(
        self, *, commit_sha: str, max_paths: int
    ) -> object: ...


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

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None: ...

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str: ...
