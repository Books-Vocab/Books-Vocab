"""Read-only branch content review packets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from ..domain.branch_content import (
    BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT,
    BRANCH_REVIEW_PATH_LIMIT,
    BranchContentEvidence,
    validate_branch_content_limit,
)
from ..domain.errors import DeliverySourceError, InvalidReceipt
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
        max_commit_summaries: int = BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT,
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
        max_commit_summaries: int = BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT,
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
    def compact_for_review(
        evidence: BranchContentEvidence,
        *,
        max_paths: int = BRANCH_REVIEW_PATH_LIMIT,
    ) -> BranchContentEvidence:
        """Keep review-plan transport bounded without weakening evidence.

        The full path count and content fingerprint remain authoritative.  A
        caller that needs more path detail can use the single-branch inspect
        command; review plans only need a small deterministic sample per item.
        """

        try:
            bounded_max_paths = validate_branch_content_limit(
                max_paths,
                field="review path limit",
                maximum=BRANCH_REVIEW_PATH_LIMIT,
            )
        except InvalidReceipt as error:
            raise ValueError(str(error)) from error
        if len(evidence.changed_paths) <= bounded_max_paths:
            return evidence
        return replace(
            evidence,
            changed_paths=evidence.changed_paths[:bounded_max_paths],
            changed_paths_truncated=True,
        )

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
