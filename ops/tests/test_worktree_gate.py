from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import worktree_gate as MODULE  # noqa: E402


def test_coverage_partitions_covered_neutral_and_uncovered() -> None:
    result = MODULE.coverage(
        ["backend/src.py", ".claude/skills/example.md", "mystery.txt"],
        {"backend/src.py"},
    )

    assert result == {
        "covered": ["backend/src.py"],
        "neutral": [[".claude/skills/example.md", ".claude/"]],
        "uncovered": ["mystery.txt"],
    }


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([], "pass"),
        ([{"status": "pass"}, {"status": "warn"}], "warn"),
        ([{"status": "inconclusive"}], "warn"),
        ([{"status": "block"}], "block"),
        ([{"name": "unknown", "status": "timeout"}], "block"),
    ],
)
def test_aggregate_verdict_keeps_closed_status_contract(
    results: list[dict[str, object]], expected: str
) -> None:
    assert MODULE.aggregate_verdict(results) == expected
