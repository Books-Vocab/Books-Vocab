"""Read-only branch content review packets."""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.branch_content import BranchContentEvidence
from ..domain.errors import DeliverySourceError
from ..ports.git import BranchContentQueryPort


class BranchContentService:
    """Build bounded evidence without claiming ownership or changing refs."""

    def __init__(self, *, git: BranchContentQueryPort) -> None:
        self.git = git

    def inspect(
        self,
        *,
        branch: str,
        base_sha: str,
        max_commit_summaries: int = 20,
    ) -> BranchContentEvidence:
        try:
            return self.git.inspect_branch_content(
                branch=branch,
                base_sha=base_sha,
                max_commit_summaries=max_commit_summaries,
            )
        except DeliverySourceError as error:
            return self._error(
                branch=branch,
                base_sha=base_sha,
                error=str(error),
            )

    def inspect_many(
        self,
        *,
        branches: Iterable[str],
        base_sha: str,
        max_commit_summaries: int = 20,
    ) -> dict[str, BranchContentEvidence]:
        return {
            branch: self.inspect(
                branch=branch,
                base_sha=base_sha,
                max_commit_summaries=max_commit_summaries,
            )
            for branch in dict.fromkeys(branches)
        }

    @staticmethod
    def _error(*, branch: str, base_sha: str, error: str) -> BranchContentEvidence:
        return BranchContentEvidence(
            schema="kg.delivery.branch-content.v1",
            branch=branch,
            base_sha=base_sha,
            head_sha="0" * 40,
            base_is_ancestor=None,
            ahead_commit_count=0,
            behind_commit_count=0,
            changed_paths=(),
            changed_path_count=0,
            changed_paths_truncated=False,
            change_fingerprint="error",
            commit_subjects=(),
            commit_subjects_truncated=False,
            complete=False,
            error=error,
        )


__all__ = ["BranchContentService"]
