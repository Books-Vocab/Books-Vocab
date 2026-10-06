"""Read-only inspection of unreachable Git commit objects."""

from __future__ import annotations

from ..domain.errors import DeliverySourceError
from ..domain.unreachable_commits import (
    UNREACHABLE_COMMIT_PATH_LIMIT,
    UnreachableCommitEvidence,
)
from ..ports.git import UnreachableCommitQueryPort


class UnreachableCommitService:
    """Keep unreachable-object evidence separate from delivery ownership."""

    def __init__(self, *, git: UnreachableCommitQueryPort) -> None:
        self.git = git

    def inspect(
        self,
        commit_sha: str,
        *,
        max_paths: int = UNREACHABLE_COMMIT_PATH_LIMIT,
    ) -> UnreachableCommitEvidence:
        try:
            return self.git.inspect_unreachable_commit(
                commit_sha=commit_sha,
                max_paths=max_paths,
            )
        except DeliverySourceError as error:
            return UnreachableCommitEvidence(
                schema="kg.delivery.unreachable-commit.v1",
                commit_sha=commit_sha,
                parent_shas=(),
                subject=None,
                unreachable=None,
                changed_paths=(),
                changed_path_count=0,
                changed_paths_truncated=False,
                change_fingerprint=None,
                disposition="source_problem",
                source_problem_scope="unknown",
                next_step="repair Git source evidence before any owner or cleanup decision",
                complete=False,
                error=str(error),
            )


__all__ = ["UnreachableCommitService"]
