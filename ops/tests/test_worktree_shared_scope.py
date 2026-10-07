from __future__ import annotations

import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry
from lib import worktree_scope
from lib.worktree_scope import SHARED_SCOPE_FILES
from worktree_registry_core import records as records_module


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


def test_allowlist_is_exact_existing_canonical_paths() -> None:
    root = OPS.parent
    for path in SHARED_SCOPE_FILES:
        assert worktree_scope._normalise_path(path) == (path, None), path
        assert "*" not in path and "?" not in path and "[" not in path, path
        assert (root / path).is_file(), f"stale allowlist entry: {path}"
    assert SHARED_SCOPE_FILES == {
        "docs/reference/tech_index.md",
        "docs/registry.yml",
        "ops/complexity_budget.json",
    }


def test_overlap_paths_subtracts_only_exact_allowlisted_files() -> None:
    shared = "ops/complexity_budget.json"
    assert worktree_scope.overlap_paths({shared, "ops/a.py"}, {shared}) == set()
    assert worktree_scope.overlap_paths({shared, "ops/a.py"}, [shared, "ops/a.py"]) == {
        "ops/a.py"
    }
    # Same directory / look-alike names stay exclusive.
    assert (
        worktree_scope.overlap_paths({"ops/complexity_budget.json.bak"}, {shared})
        == set()
    )
    assert worktree_scope.overlap_paths({"ops/other.json"}, {"ops/other.json"}) == {
        "ops/other.json"
    }


def _scope_arg(*paths: str) -> str:
    return json.dumps(
        {
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": p, "operation": "modify"} for p in paths],
        }
    )


def _scope_set(state_path: Path, tmp_path: Path, name: str, *paths: str) -> int:
    return registry.main(
        [
            "scope-set",
            "--state",
            str(state_path),
            "--branch",
            f"feat/{name}",
            "--path",
            str(tmp_path / name),
            "--scope",
            _scope_arg(*paths),
            "--json",
        ]
    )


def _two_active_lanes(tmp_path: Path) -> Path:
    state_path = tmp_path / "registry.json"
    records = [
        {
            "branch": f"feat/{name}",
            "path": str(tmp_path / name),
            "status": "active",
            "external_ids": [name.upper()],
            "scope": json.loads(_scope_arg(*paths)),
            "claim_generation": 1,
        }
        for name, paths in (
            ("one", ("ops/complexity_budget.json", "ops/a.py")),
            ("two", ("ops/b.py",)),
        )
    ]
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": records})
    return state_path


def test_scope_set_allows_shared_overlap_and_records_it_exactly(
    tmp_path: Path, capsys
) -> None:
    state_path = _two_active_lanes(tmp_path)

    rc = _scope_set(
        state_path, tmp_path, "two", "ops/complexity_budget.json", "ops/b.py"
    )

    capsys.readouterr()
    assert rc == registry.EXIT_OK
    stored = registry.load_state(state_path)["records"][1]["scope"]["files"]
    assert [item["path"] for item in stored] == [
        "ops/complexity_budget.json",
        "ops/b.py",
    ]


def test_scope_set_still_refuses_exclusive_overlap_beside_shared_file(
    tmp_path: Path, capsys
) -> None:
    state_path = _two_active_lanes(tmp_path)

    rc = _scope_set(
        state_path, tmp_path, "two", "ops/complexity_budget.json", "ops/a.py"
    )

    out = json.loads(capsys.readouterr().out)
    assert rc == registry.EXIT_CLAIMED
    assert out["owners"][0]["scope_paths"] == ["ops/a.py"]


def test_malformed_record_sharing_only_an_allowlisted_file_is_not_a_blocker() -> None:
    shared = "ops/complexity_budget.json"
    state = {
        "records": [
            {
                "branch": "feat/x",
                "path": "/tmp/x",
                "scope": json.loads(_scope_arg(shared)),
            }
        ]
    }
    problem = {"kind": "record-malformed", "index": 0}

    def overlaps(*paths: str) -> bool:
        return records_module._problem_overlaps_target(
            state,
            problem,
            branch="feat/y",
            path="/tmp/y",
            external_ids_value=None,
            scope=json.loads(_scope_arg(*paths)),
        )

    assert overlaps(shared) is False
    assert overlaps(shared, "ops/a.py") is False
    state["records"][0]["scope"] = json.loads(_scope_arg(shared, "ops/a.py"))
    assert overlaps(shared, "ops/a.py") is True
