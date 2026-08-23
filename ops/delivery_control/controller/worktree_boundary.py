"""Explicit boundary between delivery worktrees and supervision checkouts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..domain.observations import PhysicalWorktree


@dataclass(frozen=True)
class WorktreePartition:
    """A read-only classification based on an explicit supervision manifest."""

    delivery: tuple[PhysicalWorktree, ...]
    supervision: tuple[PhysicalWorktree, ...]
    canonical_count: int


def partition_worktrees(
    worktrees: Iterable[PhysicalWorktree],
    *,
    canonical_path: Path,
    supervision_paths: Iterable[Path] = (),
) -> WorktreePartition:
    """Classify exact paths; unknown worktrees remain delivery inventory.

    The caller must provide supervision paths from the runtime launch manifest.
    No path-prefix or directory-name heuristic is allowed because that could
    hide an unowned product worktree from readiness checks.
    """

    canonical = canonical_path.resolve()
    supervision = {path.resolve() for path in supervision_paths}
    records = tuple(worktrees)
    supervision_records = tuple(
        item for item in records if item.path.resolve() in supervision
    )
    delivery_records = tuple(
        item for item in records if item.path.resolve() not in supervision
    )
    return WorktreePartition(
        delivery=delivery_records,
        supervision=supervision_records,
        canonical_count=sum(
            item.path.resolve() == canonical for item in delivery_records
        ),
    )
