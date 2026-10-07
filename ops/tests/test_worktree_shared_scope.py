from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry
from lib.worktree_scope import SHARED_SCOPE_FILES


def _register(state: dict, name: str, tmp_path: Path, *paths: str) -> tuple[int, dict]:
    return registry._register_record(
        state,
        branch=f"feat/{name}",
        path=str(tmp_path / name),
        intent=name,
        base="main",
        external_ids=[],
        scope={
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": p, "operation": "modify"} for p in paths],
        },
    )


def test_shared_allowlisted_files_do_not_serialize_lanes(tmp_path: Path) -> None:
    assert "ops/complexity_budget.json" in SHARED_SCOPE_FILES
    state = {"schema": registry.SCHEMA, "records": []}
    first_rc, _ = _register(
        state, "one", tmp_path, "ops/complexity_budget.json", "ops/a.py"
    )
    second_rc, refusal = _register(
        state, "two", tmp_path, "ops/complexity_budget.json", "ops/b.py"
    )

    assert first_rc == registry.EXIT_OK
    assert second_rc == registry.EXIT_OK, refusal
    # Still recorded exactly in Scope; only exempt from exclusivity.
    recorded = state["records"][1]["scope"]["files"]
    assert {"path": "ops/complexity_budget.json", "operation": "modify"} in recorded


def test_shared_file_exemption_does_not_hide_real_overlap(tmp_path: Path) -> None:
    state = {"schema": registry.SCHEMA, "records": []}
    _register(state, "one", tmp_path, "ops/complexity_budget.json", "ops/a.py")
    rc, refusal = _register(
        state, "two", tmp_path, "ops/complexity_budget.json", "ops/a.py"
    )

    assert rc == registry.EXIT_CLAIMED
    assert refusal["owners"][0]["scope_paths"] == ["ops/a.py"]


def test_non_allowlisted_file_stays_exclusive(tmp_path: Path) -> None:
    state = {"schema": registry.SCHEMA, "records": []}
    _register(state, "one", tmp_path, "ops/other.py")
    rc, _ = _register(state, "two", tmp_path, "ops/other.py")
    assert rc == registry.EXIT_CLAIMED


def test_allowlist_is_exact_paths_only() -> None:
    assert all("*" not in p and not p.endswith("/") for p in SHARED_SCOPE_FILES)
