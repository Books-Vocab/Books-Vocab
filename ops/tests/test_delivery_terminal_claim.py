from __future__ import annotations

import pytest
from delivery_control.adapters.errors import AdapterPayloadError
from delivery_control.adapters.registry_query import terminal_claim

BASE = "a" * 40
HEAD = "b" * 40
BRANCH = "debug/legacy"
SCOPE = {
    "schema": "kg.worktree.scope.v1",
    "files": [{"operation": "modify", "path": "ops/example.py"}],
}


def _record(
    *,
    base: str = BASE,
    handed_back_sha: str | None = None,
    claim_generation: int = 1,
) -> dict[str, object]:
    return {
        "branch": BRANCH,
        "path": "/tmp/legacy-terminal",
        "status": "abandoned",
        "external_ids": ["#1"],
        "base_sha": base,
        "scope": SCOPE,
        "claim_generation": claim_generation,
        "handed_back_sha": handed_back_sha,
    }


def test_terminal_claim_selects_unique_handback_from_duplicate_history() -> None:
    historical = _record(base="c" * 40, claim_generation=0)
    current = _record(handed_back_sha=HEAD, claim_generation=1)

    record = terminal_claim(
        {"records": [historical, historical, historical, current]}, branch=BRANCH
    )

    assert record is not None
    assert record.claim_generation == 1
    assert record.handed_back_sha == HEAD


def test_terminal_claim_rejects_multiple_handback_proofs() -> None:
    with pytest.raises(AdapterPayloadError, match="multiple registry claims"):
        terminal_claim(
            {
                "records": [
                    _record(handed_back_sha=HEAD, claim_generation=0),
                    _record(handed_back_sha="c" * 40, claim_generation=1),
                ]
            },
            branch=BRANCH,
        )


def test_terminal_claim_rejects_ambiguous_history_without_handback() -> None:
    with pytest.raises(AdapterPayloadError, match="multiple registry claims"):
        terminal_claim(
            {"records": [_record(claim_generation=0), _record(claim_generation=1)]},
            branch=BRANCH,
        )


def test_terminal_claim_ignores_unrelated_malformed_history() -> None:
    record = terminal_claim(
        {"records": [{"branch": "broken"}, _record()]}, branch=BRANCH
    )

    assert record is not None
    assert record.branch == BRANCH
