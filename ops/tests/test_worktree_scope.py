from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib.worktree_scope import normalise_scope, scope_problems


def test_worktree_scope_accepts_canonical_delete_operation() -> None:
    payload = {
        "schema": "kg.worktree.scope.v1",
        "files": [
            {"operation": "delete", "path": "ops/old.py"},
            {"operation": "add", "path": "ops/new.py"},
        ],
    }

    assert scope_problems(payload) == []
    assert normalise_scope(payload) == payload


def test_worktree_scope_accepts_create_as_alias_of_add() -> None:
    payload = {"files": [{"operation": "create", "path": "ops/new.py"}]}

    assert normalise_scope(payload) == {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ops/new.py", "operation": "add"}],
    }
    # Validation of stored records stays strict: the alias is input-only.
    assert scope_problems(payload)[0]["kind"] == "scope-file-bad-operation"


def test_worktree_scope_bad_operation_suggests_closest_value() -> None:
    problems = scope_problems({"files": [{"operation": "modifiy", "path": "ops/a.py"}]})

    assert problems[0]["suggestion"] == "modify"
    try:
        normalise_scope({"files": [{"operation": "bogus", "path": "ops/a.py"}]})
    except ValueError as exc:
        assert "allowed" in str(exc) and "'add'" in str(exc)
    else:
        raise AssertionError("bogus operation must be rejected")
