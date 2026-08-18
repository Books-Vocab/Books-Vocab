from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry  # noqa: E402


def _state() -> dict:
    return {"schema": registry.SCHEMA, "records": []}


def test_register_keeps_external_reference_opaque_and_detects_collision(tmp_path: Path) -> None:
    state = _state()
    rc, first = registry._register_record(
        state, branch="feat/one", path=str(tmp_path / "one"), intent="feature",
        base="main", external_ids=["#123"], scope=None,
    )
    assert rc == registry.EXIT_OK
    assert first["external_ids"] == ["#123"]

    rc, refused = registry._register_record(
        state, branch="feat/two", path=str(tmp_path / "two"), intent="feature",
        base="main", external_ids=["#123"], scope=None,
    )
    assert rc == registry.EXIT_CLAIMED
    assert refused["owners"][0]["branch"] == "feat/one"


def test_load_state_migrates_live_machine_claim_without_recreating_a_store(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"records": [{
        "branch": "feat/live", "path": str(tmp_path / "live"),
        "status": "active", "backlog": ["#7"],
    }]}), encoding="utf-8")
    state = registry.load_state(path)
    assert state["records"][0]["external_ids"] == ["#7"]
    assert "backlog" not in state["records"][0]


def test_scope_set_rejects_duplicate_file_declarations() -> None:
    with pytest.raises(ValueError, match="invalid scope"):
        registry.normalise_scope({
            "schema": "kg.worktree.scope.v1",
            "files": [
                {"path": "backend/app.py", "operation": "modify"},
                {"path": "backend/app.py", "operation": "modify"},
            ],
        })


def test_handback_seal_digest_is_verifiable() -> None:
    record = {"branch": "feat/seal", "path": "/tmp/seal", "external_ids": ["#9"]}
    body = registry._seal_body(
        record, base_sha="a" * 40, tip_sha="b" * 40,
        outcomes=[{"id": "#9", "status": "pass"}],
        handed_back_at="2026-08-19T00:00:00Z",
    )
    record["handback_seal"] = registry._seal_with_digest(body)
    assert registry.validate_handback_seal(record) == []
    record["handback_seal"]["tip_sha"] = "c" * 40
    assert {item["kind"] for item in registry.validate_handback_seal(record)} == {
        "handback-seal-digest-invalid"
    }
