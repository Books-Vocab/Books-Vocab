"""Typed read-only evidence for a local branch that is not yet landed."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InvalidReceipt

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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


__all__ = ["BranchContentEvidence"]
