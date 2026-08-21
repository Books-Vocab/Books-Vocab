from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import InvalidReceipt, InvalidScope
from delivery_control.domain.models import (
    HandbackReceipt,
    Scope,
    ScopeFile,
    ScopeOperation,
    ValidationEvidence,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
ORIGIN_SHA = "c" * 40
DIGEST = "d" * 64


def test_scope_is_canonical_and_has_a_stable_digest() -> None:
    scope = Scope(
        files=(
            ScopeFile(ScopeOperation.MODIFY, "ops/z.py"),
            ScopeFile(ScopeOperation.ADD, "ops/a.py"),
        )
    )

    assert [item.path for item in scope.files] == ["ops/a.py", "ops/z.py"]
    assert scope.to_payload() == {
        "schema": "kg.worktree.scope.v1",
        "files": [
            {"operation": "add", "path": "ops/a.py"},
            {"operation": "modify", "path": "ops/z.py"},
        ],
    }
    assert scope.digest == Scope(scope.files).digest


@pytest.mark.parametrize(
    "path",
    ["", "/absolute.py", "../escape.py", "ops/../escape.py", "./ops/file.py"],
)
def test_scope_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(InvalidScope):
        Scope(files=(ScopeFile(ScopeOperation.MODIFY, path),))


def test_scope_rejects_duplicate_paths_even_when_operations_differ() -> None:
    with pytest.raises(InvalidScope, match="duplicate"):
        Scope(
            files=(
                ScopeFile(ScopeOperation.ADD, "ops/a.py"),
                ScopeFile(ScopeOperation.MODIFY, "ops/a.py"),
            )
        )


def test_handback_receipt_round_trips_as_typed_canonical_payload() -> None:
    scope = Scope.from_paths(modify=("ops/a.py",), add=("ops/b.py",))
    evidence = ValidationEvidence(
        command=("uv", "run", "pytest", "ops/tests/test_a.py"),
        exit_code=0,
        duration_seconds=1.25,
        observed_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
    )
    receipt = HandbackReceipt(
        lane_id="DIRECT-1",
        owner_thread_id="thread-1",
        branch="feat/example",
        worktree_path="/tmp/example",
        base_sha=BASE_SHA,
        parent_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        origin_main_sha=ORIGIN_SHA,
        content_digest=DIGEST,
        scope=scope,
        validation=(evidence,),
    )

    payload = receipt.to_payload()

    assert payload["schema"] == "kg.worktree.handback.v1"
    assert payload["base_sha"] == BASE_SHA
    assert payload["origin_main_sha"] == ORIGIN_SHA
    assert payload["scope_digest"] == scope.digest
    assert payload["validation"][0]["command"] == [
        "uv",
        "run",
        "pytest",
        "ops/tests/test_a.py",
    ]
    assert HandbackReceipt.from_payload(payload) == receipt


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_sha", "short"),
        ("parent_sha", "g" * 40),
        ("head_sha", ""),
        ("origin_main_sha", "x" * 40),
        ("content_digest", "0" * 63),
    ],
)
def test_handback_receipt_rejects_invalid_identity_fields(
    field: str, value: str
) -> None:
    values: dict[str, object] = {
        "lane_id": "DIRECT-1",
        "owner_thread_id": "thread-1",
        "branch": "feat/example",
        "worktree_path": "/tmp/example",
        "base_sha": BASE_SHA,
        "parent_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "origin_main_sha": ORIGIN_SHA,
        "content_digest": DIGEST,
        "scope": Scope.from_paths(modify=("ops/a.py",)),
    }
    values[field] = value

    with pytest.raises(InvalidReceipt):
        HandbackReceipt(**values)  # type: ignore[arg-type]
