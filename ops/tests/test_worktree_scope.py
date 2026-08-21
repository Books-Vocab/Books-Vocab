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
