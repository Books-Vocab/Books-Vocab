"""Typed read-only evidence for a local branch that is not yet landed."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InvalidReceipt

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_CONTENT_PATH_LIMIT = 200
BRANCH_REVIEW_PAGE_LIMIT = 5
BRANCH_REVIEW_PATH_LIMIT = 20


def _sha(value: str, field: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise InvalidReceipt(f"{field} must be a lowercase commit SHA")
    return value


def _text(value: str, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise InvalidReceipt(f"{field} must be canonical text")
    return value


@dataclass(frozen=True)
class BranchContentEvidence:
    """Bounded evidence used to choose publish, preserve, or explicit discard.

    This is intentionally not a delivery claim.  It contains enough immutable
    evidence to review an unlanded local branch without treating its presence as
    active development or silently deleting its commits.
    """

    schema: str
    branch: str
    base_sha: str
    head_sha: str
    base_is_ancestor: bool | None
    ahead_commit_count: int
    behind_commit_count: int
    changed_paths: tuple[str, ...]
    changed_path_count: int
    changed_paths_truncated: bool
    change_fingerprint: str
    commit_subjects: tuple[str, ...]
    commit_subjects_truncated: bool
    complete: bool
    error: str | None = None

    def __post_init__(self) -> None:
        _text(self.schema, "content evidence schema")
        _text(self.branch, "content evidence branch")
        _sha(self.base_sha, "content evidence base")
        _sha(self.head_sha, "content evidence head")
        if self.base_is_ancestor not in (True, False, None):
            raise InvalidReceipt("content evidence ancestor flag is invalid")
        for field in ("ahead_commit_count", "behind_commit_count"):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise InvalidReceipt(f"{field} must be a non-negative integer")
        if type(self.changed_paths) is not tuple or any(
            type(path) is not str or not path for path in self.changed_paths
        ):
            raise InvalidReceipt("content evidence changed paths are invalid")
        if tuple(sorted(set(self.changed_paths))) != self.changed_paths:
            raise InvalidReceipt("content evidence changed paths are not canonical")
        if type(self.changed_path_count) is not int or self.changed_path_count < len(
            self.changed_paths
        ):
            raise InvalidReceipt("content evidence changed path count is invalid")
        if self.changed_paths_truncated != (
            self.changed_path_count > len(self.changed_paths)
        ):
            raise InvalidReceipt("content evidence path truncation is inconsistent")
        _text(self.change_fingerprint, "content evidence change fingerprint")
        if type(self.commit_subjects) is not tuple or any(
            type(subject) is not str or not subject for subject in self.commit_subjects
        ):
            raise InvalidReceipt("content evidence commit subjects are invalid")
        if type(self.commit_subjects_truncated) is not bool:
            raise InvalidReceipt("content evidence truncation flag is invalid")
        if type(self.complete) is not bool:
            raise InvalidReceipt("content evidence complete flag is invalid")
        if self.error is not None:
            _text(self.error, "content evidence error")

    @property
    def unlanded(self) -> bool:
        return self.base_is_ancestor is False and self.ahead_commit_count > 0


@dataclass(frozen=True)
class BranchContentReviewItem:
    """One paged, read-only review item for a blocked local orphan."""

    schema: str
    branch: str
    expected_head_sha: str
    preflight_eligible: bool
    preflight_blockers: tuple[str, ...]
    content: BranchContentEvidence
    next_step: str

    def __post_init__(self) -> None:
        _text(self.schema, "branch review item schema")
        _text(self.branch, "branch review item branch")
        _sha(self.expected_head_sha, "branch review item expected head")
        if type(self.preflight_eligible) is not bool:
            raise InvalidReceipt("branch review item eligibility is invalid")
        if type(self.preflight_blockers) is not tuple or any(
            type(item) is not str or not item for item in self.preflight_blockers
        ):
            raise InvalidReceipt("branch review item blockers are invalid")
        if tuple(sorted(set(self.preflight_blockers))) != self.preflight_blockers:
            raise InvalidReceipt("branch review item blockers are not canonical")
        if self.preflight_eligible and self.preflight_blockers:
            raise InvalidReceipt(
                "eligible branch review item cannot contain preflight blockers"
            )
        if not isinstance(self.content, BranchContentEvidence):
            raise InvalidReceipt("branch review item content is invalid")
        if self.content.branch != self.branch:
            raise InvalidReceipt("branch review item content branch differs")
        if self.content.head_sha != self.expected_head_sha:
            raise InvalidReceipt("branch review item content HEAD differs")
        _text(self.next_step, "branch review item next step")


@dataclass(frozen=True)
class BranchContentReviewPlan:
    """A bounded page over local orphan content; it never authorizes deletion.

    ``reviewable_complete`` is deliberately separate from ``complete``.  The
    former says that this invocation started at the first page and exhausted
    the reviewable orphan queue with complete content evidence.  The latter
    additionally requires the complete branch audit, including assets that are
    intentionally excluded from this review queue.
    """

    schema: str
    live_main_sha: str | None
    audit_complete: bool
    complete: bool
    offset: int
    limit: int
    total_candidates: int
    reviewed_count: int
    remaining_count: int
    source_problem_count: int
    items: tuple[BranchContentReviewItem, ...]
    reviewable_complete: bool | None = None

    def __post_init__(self) -> None:
        _text(self.schema, "branch review plan schema")
        if self.live_main_sha is not None:
            _sha(self.live_main_sha, "branch review plan live main")
        if type(self.audit_complete) is not bool or type(self.complete) is not bool:
            raise InvalidReceipt("branch review plan completeness is invalid")
        for field in (
            "offset",
            "limit",
            "total_candidates",
            "reviewed_count",
            "remaining_count",
            "source_problem_count",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise InvalidReceipt(f"branch review plan {field} is invalid")
        if self.limit == 0:
            raise InvalidReceipt("branch review plan limit must be positive")
        if self.reviewed_count != self.offset + len(self.items):
            raise InvalidReceipt("branch review plan reviewed count is inconsistent")
        if self.remaining_count != max(self.total_candidates - self.reviewed_count, 0):
            raise InvalidReceipt("branch review plan remaining count is inconsistent")
        if len(self.items) > self.limit:
            raise InvalidReceipt("branch review plan exceeds its page limit")
        expected_reviewable_complete = (
            self.live_main_sha is not None
            and self.offset == 0
            and self.remaining_count == 0
            and all(item.content.complete for item in self.items)
        )
        if self.reviewable_complete is not None:
            if type(self.reviewable_complete) is not bool:
                raise InvalidReceipt(
                    "branch review plan reviewable completeness is invalid"
                )
            if self.reviewable_complete != expected_reviewable_complete:
                raise InvalidReceipt(
                    "branch review plan reviewable completeness is inconsistent"
                )
        if self.complete != (self.audit_complete and expected_reviewable_complete):
            raise InvalidReceipt("branch review plan completeness is inconsistent")


__all__ = [
    "BRANCH_CONTENT_PATH_LIMIT",
    "BRANCH_REVIEW_PAGE_LIMIT",
    "BRANCH_REVIEW_PATH_LIMIT",
    "BranchContentEvidence",
    "BranchContentReviewItem",
    "BranchContentReviewPlan",
]
