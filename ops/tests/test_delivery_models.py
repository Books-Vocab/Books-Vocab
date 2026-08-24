from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain import (
    handback_models,
    models as models_facade,
    scope_models,
    terminal_proof_models,
    validation_models,
)
from delivery_control.domain.errors import InvalidReceipt, InvalidScope
from delivery_control.domain.models import (
    CheckStatus,
    HANDBACK_SCHEMA,
    HandbackOutcome,
    HandbackReceipt,
    MergedPullRequestProof,
    SCOPE_SCHEMA,
    Scope,
    ScopeFile,
    ScopeOperation,
    ValidationEvidence,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
ORIGIN_SHA = "c" * 40
DIGEST = "d" * 64


def test_models_facade_preserves_public_imports_as_exact_aliases() -> None:
    assert HANDBACK_SCHEMA == handback_models.HANDBACK_SCHEMA
    assert SCOPE_SCHEMA == scope_models.SCOPE_SCHEMA
    assert HandbackReceipt is handback_models.HandbackReceipt
    assert MergedPullRequestProof is terminal_proof_models.MergedPullRequestProof
    assert Scope is scope_models.Scope
    assert ScopeFile is scope_models.ScopeFile
    assert ScopeOperation is scope_models.ScopeOperation
    assert CheckStatus is validation_models.CheckStatus
    assert HandbackOutcome is validation_models.HandbackOutcome
    assert ValidationEvidence is validation_models.ValidationEvidence
    assert models_facade.HandbackReceipt is HandbackReceipt
    assert models_facade.Scope is Scope
    assert models_facade._has_control is validation_models._has_control
    assert models_facade._require_sha is validation_models._require_sha
    assert models_facade._safe_relative_path is scope_models._safe_relative_path


def test_merged_pr_proof_is_exact_and_main_only() -> None:
    proof = MergedPullRequestProof(
        lane_id="ISSUE-1",
        pr_number=42,
        branch="feat/one",
        head_sha=HEAD_SHA,
    )

    assert proof.base_branch == "main"
    assert proof.pr_state == "MERGED"
    with pytest.raises(InvalidReceipt, match="target main"):
        MergedPullRequestProof(
            lane_id="ISSUE-1",
            pr_number=42,
            branch="feat/one",
            head_sha=HEAD_SHA,
            base_branch="release",
        )


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


def test_scope_delete_round_trips_without_changing_the_v1_wire_shape() -> None:
    scope = Scope.from_paths(
        delete=("ops/old.py",),
        add=("ops/new.py",),
    )

    assert scope.to_payload() == {
        "schema": "kg.worktree.scope.v1",
        "files": [
            {"operation": "add", "path": "ops/new.py"},
            {"operation": "delete", "path": "ops/old.py"},
        ],
    }
    assert Scope.from_payload(scope.to_payload()) == scope
    assert scope.paths == ("ops/new.py", "ops/old.py")


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
        claim_generation=3,
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

    assert payload["schema"] == "kg.delivery.handback.v1"
    assert payload["base_sha"] == BASE_SHA
    assert payload["claim_generation"] == 3
    assert payload["origin_main_sha"] == ORIGIN_SHA
    assert payload["scope_digest"] == scope.digest
    assert payload["validation"][0]["command"] == [
        "uv",
        "run",
        "pytest",
        "ops/tests/test_a.py",
    ]
    assert HandbackReceipt.from_payload(payload) == receipt


@pytest.mark.parametrize("payload", [[], "not-an-object", None])
def test_handback_receipt_rejects_non_object_payloads(payload: object) -> None:
    with pytest.raises(InvalidReceipt, match="handback receipt"):
        HandbackReceipt.from_payload(payload)  # type: ignore[arg-type]


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
        "claim_generation": 0,
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


@pytest.mark.parametrize("path", ["ops/\x00bad.py", "ops/\nbad.py", "ops/\tbad.py"])
def test_scope_rejects_control_characters(path: str) -> None:
    with pytest.raises(InvalidScope):
        Scope.from_paths(modify=(path,))


@pytest.mark.parametrize(
    "payload_patch",
    [
        {"exit_code": 1.5},
        {"duration_seconds": float("nan")},
        {"duration_seconds": 1},
        {"observed_at": "2026-08-21T12:00:00"},
    ],
)
def test_validation_evidence_rejects_loose_or_non_finite_values(
    payload_patch: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "command": ["uv", "run", "pytest"],
        "exit_code": 0,
        "duration_seconds": 1.0,
        "observed_at": "2026-08-21T12:00:00+00:00",
    }
    payload.update(payload_patch)
    with pytest.raises(InvalidReceipt):
        ValidationEvidence.from_payload(payload)


def test_internal_handback_schema_does_not_accept_legacy_registry_seal() -> None:
    legacy = {
        "schema": "kg.worktree.handback.v1",
        "branch": "feat/example",
        "path": "/tmp/example",
        "tip_sha": HEAD_SHA,
        "digest": DIGEST,
    }
    with pytest.raises(InvalidReceipt, match="kg.delivery.handback.v1"):
        HandbackReceipt.from_payload(legacy)
