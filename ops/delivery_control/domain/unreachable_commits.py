"""Typed, read-only facts about Git commits that have no observed ref."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InvalidReceipt

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
UNREACHABLE_COMMIT_SAMPLE_SIZE = 20
UNREACHABLE_COMMIT_PATH_LIMIT = 200


def _text(value: str, field: str) -> None:
    if (
        type(value) is not str
        or not value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise InvalidReceipt(f"{field} must be canonical text")


@dataclass(frozen=True)
class UnreachableCommitEvidence:
    """Bounded evidence for one unreachable commit object.

    This is deliberately an observation, not a branch, owner, Issue, or PR
    claim.  A confirmed object is preserved for correlation before any
    lifecycle action can be considered.
    """

    schema: str
    commit_sha: str
    parent_shas: tuple[str, ...]
    subject: str | None
    unreachable: bool | None
    changed_paths: tuple[str, ...]
    changed_path_count: int
    changed_paths_truncated: bool
    change_fingerprint: str | None
    disposition: str
    source_problem_scope: str | None
    next_step: str
    complete: bool
    error: str | None = None

    def __post_init__(self) -> None:
        _text(self.schema, "unreachable commit evidence schema")
        if _SHA_RE.fullmatch(self.commit_sha) is None:
            raise InvalidReceipt("unreachable commit evidence SHA is malformed")
        if type(self.parent_shas) is not tuple or any(
            _SHA_RE.fullmatch(parent) is None for parent in self.parent_shas
        ):
            raise InvalidReceipt("unreachable commit evidence parents are malformed")
        if len(set(self.parent_shas)) != len(self.parent_shas):
            raise InvalidReceipt("unreachable commit evidence parents are duplicated")
        if self.subject is not None:
            _text(self.subject, "unreachable commit subject")
        if self.unreachable not in (True, False, None):
            raise InvalidReceipt("unreachable commit confirmation is invalid")
        if type(self.changed_paths) is not tuple or any(
            type(path) is not str or not path for path in self.changed_paths
        ):
            raise InvalidReceipt("unreachable commit changed paths are invalid")
        if tuple(sorted(set(self.changed_paths))) != self.changed_paths:
            raise InvalidReceipt("unreachable commit changed paths are not canonical")
        if type(self.changed_path_count) is not int or self.changed_path_count < len(
            self.changed_paths
        ):
            raise InvalidReceipt("unreachable commit changed path count is invalid")
        if self.changed_paths_truncated != (
            self.changed_path_count > len(self.changed_paths)
        ):
            raise InvalidReceipt("unreachable commit path truncation is inconsistent")
        if (
            self.change_fingerprint is not None
            and _DIGEST_RE.fullmatch(self.change_fingerprint) is None
        ):
            raise InvalidReceipt("unreachable commit fingerprint is malformed")
        if self.disposition not in {
            "preserve_for_owner_correlation",
            "preserve_with_source_problem",
            "refuse_not_unreachable",
            "source_problem",
        }:
            raise InvalidReceipt("unreachable commit disposition is invalid")
        if self.source_problem_scope not in (None, "git_objects", "unknown"):
            raise InvalidReceipt("unreachable commit source problem scope is invalid")
        if (
            self.disposition
            in {
                "source_problem",
                "preserve_with_source_problem",
            }
            and self.source_problem_scope is None
        ):
            raise InvalidReceipt(
                "source-problem evidence requires an explicit problem scope"
            )
        if self.disposition == "preserve_for_owner_correlation" and (
            self.source_problem_scope is not None
        ):
            raise InvalidReceipt(
                "clean unreachable evidence cannot carry a source problem scope"
            )
        _text(self.next_step, "unreachable commit next step")
        if type(self.complete) is not bool:
            raise InvalidReceipt("unreachable commit evidence completeness is invalid")
        if self.error is not None:
            _text(self.error, "unreachable commit evidence error")
        if self.complete and (
            self.unreachable is not True
            or self.subject is None
            or self.change_fingerprint is None
            or self.disposition
            not in {
                "preserve_for_owner_correlation",
                "preserve_with_source_problem",
            }
            or self.error is not None
        ):
            raise InvalidReceipt(
                "complete unreachable commit evidence requires confirmed unreachable object"
            )
        if self.complete is False and self.error is None:
            raise InvalidReceipt(
                "incomplete unreachable commit evidence requires an error"
            )


@dataclass(frozen=True)
class UnreachableCommitInventory:
    """Unreferenced commit objects kept in quarantine, never as delivery lanes."""

    shas: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    complete: bool = True
    evidence: tuple[UnreachableCommitEvidence, ...] = ()

    def __post_init__(self) -> None:
        if type(self.shas) is not tuple or any(
            type(sha) is not str or _SHA_RE.fullmatch(sha) is None for sha in self.shas
        ):
            raise InvalidReceipt("unreachable commit SHAs are malformed")
        if tuple(sorted(set(self.shas))) != self.shas:
            raise InvalidReceipt("unreachable commit SHAs must be sorted and unique")
        if type(self.problems) is not tuple or any(
            type(problem) is not str or not problem or "\n" in problem
            for problem in self.problems
        ):
            raise InvalidReceipt("unreachable commit problems are malformed")
        if type(self.complete) is not bool:
            raise InvalidReceipt("unreachable commit completeness must be boolean")
        if self.problems and self.complete:
            raise InvalidReceipt(
                "unreachable commit inventory with problems cannot be complete"
            )
        if not self.complete and not self.problems:
            raise InvalidReceipt(
                "incomplete unreachable commit inventory requires a problem"
            )
        if (
            type(self.evidence) is not tuple
            or len(self.evidence) > UNREACHABLE_COMMIT_SAMPLE_SIZE
        ):
            raise InvalidReceipt("unreachable commit evidence sample is invalid")
        if any(
            not isinstance(item, UnreachableCommitEvidence) for item in self.evidence
        ):
            raise InvalidReceipt("unreachable commit evidence entries are invalid")
        evidence_shas = tuple(item.commit_sha for item in self.evidence)
        if len(set(evidence_shas)) != len(evidence_shas):
            raise InvalidReceipt("unreachable commit evidence is duplicated")
        sample = self.shas[:UNREACHABLE_COMMIT_SAMPLE_SIZE]
        if any(commit_sha not in sample for commit_sha in evidence_shas):
            raise InvalidReceipt("unreachable commit evidence is outside the sample")
        if evidence_shas != tuple(
            commit_sha for commit_sha in sample if commit_sha in evidence_shas
        ):
            raise InvalidReceipt("unreachable commit evidence is not canonical")

    @property
    def count(self) -> int:
        return len(self.shas)

    @property
    def sample(self) -> tuple[str, ...]:
        return self.shas[:UNREACHABLE_COMMIT_SAMPLE_SIZE]


EMPTY_UNREACHABLE_COMMIT_INVENTORY = UnreachableCommitInventory()


__all__ = [
    "EMPTY_UNREACHABLE_COMMIT_INVENTORY",
    "UNREACHABLE_COMMIT_PATH_LIMIT",
    "UNREACHABLE_COMMIT_SAMPLE_SIZE",
    "UnreachableCommitEvidence",
    "UnreachableCommitInventory",
]
