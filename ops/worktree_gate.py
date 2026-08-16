"""Pure gate verdict and coverage helpers.

This module deliberately has no git, clock, subprocess, or repository imports.  The
orchestrator keeps compatibility wrappers for its historical private names while
the gate-specific judgement lives here as a small, directly testable seam.
"""

from __future__ import annotations

import sys
from typing import Any


NEUTRAL_RULES: tuple[tuple[str, str], ...] = (
    ("backups/", "本機備份產物，不影響任何 runtime 或 build"),
    ("promotion/", "行銷素材產物，由 catalog/App Review 平面自行驗證"),
    (".claude/", "agent / skill 文本；今天沒有任何機械內容檢查"),
    ("README.md", "根層 prose，無機械 gate"),
    (".gitignore", "不影響 runtime 或 build 行為"),
)

# The closed vocabulary a gate result may carry.  Keep this beside the aggregator
# so a new producer status cannot silently drift away from the verdict contract.
GATE_STATUSES = ("pass", "warn", "block", "inconclusive")


def neutral_rule(rel: str) -> str | None:
    """Return the declared neutral rule matching ``rel``, if any."""
    return next((pattern for pattern, _reason in NEUTRAL_RULES
                 if rel == pattern or rel.startswith(pattern)), None)


def coverage(changed_files: list[str], covered: set[str]) -> dict[str, Any]:
    """Split every changed file into covered, neutral, or uncovered.

    Coverage is visibility, not a verdict.  A routing hole must be named at the
    moment it happens; callers decide how the resulting projection affects a gate.
    """
    neutral: list[list[str]] = []
    uncovered: list[str] = []
    for rel in changed_files:
        if rel in covered:
            continue
        rule = neutral_rule(rel)
        if rule is not None:
            neutral.append([rel, rule])
        else:
            uncovered.append(rel)
    return {"covered": sorted(covered), "neutral": neutral, "uncovered": uncovered}


class UnknownGateStatus(Exception):
    """A gate reported a status outside the aggregator's closed vocabulary."""


def assert_known_statuses(results: list[dict[str, Any]]) -> None:
    """Refuse, by name, any result whose status is not in ``GATE_STATUSES``."""
    unknown = [(str(result.get("name") or "<unnamed gate>"), result.get("status"))
               for result in results if result.get("status") not in GATE_STATUSES]
    if unknown:
        detail = ", ".join(f"{name} -> {value!r}" for name, value in unknown)
        raise UnknownGateStatus(
            f"gate result(s) carry a status this aggregator has no rule for: {detail}. "
            f"Known: {', '.join(GATE_STATUSES)}. Treated as BLOCK — an aggregator that "
            "cannot read an answer has not been told the batch is fine.")


def aggregate_verdict(results: list[dict[str, Any]]) -> str:
    """Return block, warn, or pass for the supplied gate results.

    ``inconclusive`` folds to warn.  An unknown status folds to block and is named
    on stderr; silently treating an unreadable answer as green is not acceptable.
    """
    try:
        assert_known_statuses(results)
    except UnknownGateStatus as exc:
        print(f"[worktree][gate] {exc}", file=sys.stderr, flush=True)
        return "block"
    statuses = {result.get("status") for result in results}
    if "block" in statuses:
        return "block"
    if "warn" in statuses or "inconclusive" in statuses:
        return "warn"
    return "pass"
