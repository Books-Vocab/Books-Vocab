from __future__ import annotations

import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry


def _scope(path: str) -> dict:
    return {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": path, "operation": "modify"}],
    }


def test_register_rejects_scope_owned_by_another_active_claim(tmp_path: Path) -> None:
    state = {"schema": registry.SCHEMA, "records": []}
    first_rc, _ = registry._register_record(
        state,
        branch="feat/one",
        path=str(tmp_path / "one"),
        intent="one",
        base="main",
        external_ids=["ISSUE-1"],
        scope=_scope("ops/shared.py"),
    )
    second_rc, refusal = registry._register_record(
        state,
        branch="feat/two",
        path=str(tmp_path / "two"),
        intent="two",
        base="main",
        external_ids=["ISSUE-2"],
        scope=_scope("ops/shared.py"),
    )

    assert first_rc == registry.EXIT_OK
    assert second_rc == registry.EXIT_CLAIMED
    assert refusal["owners"] == [
        {
            "branch": "feat/one",
            "path": str(tmp_path / "one"),
            "status": "active",
            "external_ids": [],
            "scope_paths": ["ops/shared.py"],
        }
    ]


def test_register_rejects_scope_owned_by_cleanup_lease(tmp_path: Path) -> None:
    state = {
        "schema": registry.SCHEMA,
        "records": [
            {
                "branch": "feat/cleanup",
                "path": str(tmp_path / "cleanup"),
                "status": "cleanup_pending",
                "external_ids": ["ISSUE-1"],
                "scope": _scope("ops/shared.py"),
            }
        ],
    }

    rc, refusal = registry._register_record(
        state,
        branch="feat/new",
        path=str(tmp_path / "new"),
        intent="new",
        base="main",
        external_ids=["ISSUE-2"],
        scope=_scope("ops/shared.py"),
    )

    assert rc == registry.EXIT_CLAIMED
    assert refusal["owners"][0]["status"] == "cleanup_pending"


def test_scope_set_rejects_collision_without_invalidating_existing_seal(
    tmp_path: Path,
) -> None:
    record_one = {
        "branch": "feat/one",
        "path": str(tmp_path / "one"),
        "status": "active",
        "external_ids": ["ISSUE-1"],
        "scope": _scope("ops/one.py"),
        "claim_generation": 2,
        "handed_back_sha": "a" * 40,
        "handback_seal": {"digest": "keep"},
    }
    record_two = {
        "branch": "feat/two",
        "path": str(tmp_path / "two"),
        "status": "active",
        "external_ids": ["ISSUE-2"],
        "scope": _scope("ops/shared.py"),
        "claim_generation": 1,
    }
    state_path = tmp_path / "registry.json"
    registry.save_state(
        state_path,
        {"schema": registry.SCHEMA, "records": [record_one, record_two]},
    )

    rc = registry.main(
        [
            "scope-set",
            "--state",
            str(state_path),
            "--branch",
            "feat/one",
            "--path",
            str(tmp_path / "one"),
            "--scope",
            json.dumps(_scope("ops/shared.py")),
            "--json",
        ]
    )

    assert rc == registry.EXIT_CLAIMED
    stored = registry.load_state(state_path)["records"][0]
    assert stored["claim_generation"] == 2
    assert stored["handback_seal"] == {"digest": "keep"}
