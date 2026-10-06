"""Typed separation between actionable lanes and preserved legacy residue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IsolationSummary:
    """Read-only evidence that a lane is preserved outside the live pipeline.

    Isolation never authorizes a merge, branch deletion, owner takeover, or
    registry repair.  It only prevents proven non-runnable history from
    starving unrelated delivery lanes while keeping the raw evidence visible
    in the normal inventory and metrics output.
    """

    quarantined_source_problems: int = 0
    quarantined_blocked_lanes: int = 0
    quarantined_open_prs: int = 0
    quarantined_terminal_cleanup: int = 0

    @property
    def quarantined_lanes(self) -> int:
        return self.quarantined_blocked_lanes + self.quarantined_terminal_cleanup


EMPTY_ISOLATION = IsolationSummary()


__all__ = ["EMPTY_ISOLATION", "IsolationSummary"]
