"""Typed, read-only facts about Git commits that have no observed ref."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InvalidReceipt

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UNREACHABLE_COMMIT_SAMPLE_SIZE = 20


@dataclass(frozen=True)
class UnreachableCommitInventory:
    """Unreferenced commit objects kept in quarantine, never as delivery lanes."""

    shas: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    complete: bool = True

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

    @property
    def count(self) -> int:
        return len(self.shas)

    @property
    def sample(self) -> tuple[str, ...]:
        return self.shas[:UNREACHABLE_COMMIT_SAMPLE_SIZE]


EMPTY_UNREACHABLE_COMMIT_INVENTORY = UnreachableCommitInventory()


__all__ = [
    "EMPTY_UNREACHABLE_COMMIT_INVENTORY",
    "UNREACHABLE_COMMIT_SAMPLE_SIZE",
    "UnreachableCommitInventory",
]
