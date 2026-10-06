from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry


def test_delegation_change_advances_generation_and_invalidates_handback(
    tmp_path: Path,
) -> None:
    record = {
        "branch": "feat/delegation",
        "path": str(tmp_path / "delegation"),
        "status": "active",
        "external_ids": ["ISSUE-1"],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": "ops/a.py", "operation": "modify"}],
        },
        "codex_thread_id": "owner-one",
        "delegated": False,
        "claim_generation": 7,
        "handback_claim_generation": 7,
        "handed_back_at": "2026-08-22T00:00:00Z",
        "handed_back_sha": "a" * 40,
        "handback_seal": {"digest": "old"},
        "handback_outcomes": [{"status": "passed"}],
    }
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    rc = registry.main(
        [
            "owner-bind",
            "--state",
            str(state_path),
            "--branch",
            record["branch"],
            "--codex-thread-id",
            "owner-one",
            "--delegated",
            "--json",
        ]
    )

    assert rc == registry.EXIT_OK
    stored = registry.load_state(state_path)["records"][0]
    assert stored["delegated"] is True
    assert stored["claim_generation"] == 8
    assert stored["handed_back_at"] is None
    assert stored["handed_back_sha"] is None
    assert "handback_claim_generation" not in stored
    assert "handback_seal" not in stored
    assert "handback_outcomes" not in stored
