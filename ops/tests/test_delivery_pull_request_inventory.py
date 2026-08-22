from __future__ import annotations

import sys
from typing import Any
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
from delivery_control.adapters.github_parsing import parse_pull_request_inventory


def _pull_request(number: int, branch: str) -> dict[str, Any]:
    return {
        "id": f"PR_kwDOexample{number}",
        "number": number,
        "url": f"https://example.test/pull/{number}",
        "headRefName": branch,
        "baseRefName": "main",
        "baseRefOid": "a" * 40,
        "headRefOid": "b" * 40,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "title": f"fix: {number}",
        "body": "## Scope\n- ops/a.py\n\n## Validation\n- required",
        "autoMergeRequest": None,
    }


def test_duplicate_pull_request_number_is_source_problem() -> None:
    inventory = parse_pull_request_inventory(
        [_pull_request(42, "feat/one"), _pull_request(42, "feat/two")]
    )

    assert [item.number for item in inventory.records] == [42]
    assert inventory.problems[0].identity == "PR#42"
    assert (
        inventory.problems[0].reason
        == "GitHub PR inventory contains a duplicate number"
    )


def test_distinct_pull_request_numbers_remain_dispatchable() -> None:
    inventory = parse_pull_request_inventory(
        [_pull_request(42, "feat/one"), _pull_request(43, "feat/two")]
    )

    assert [item.number for item in inventory.records] == [42, 43]
    assert inventory.problems == ()
