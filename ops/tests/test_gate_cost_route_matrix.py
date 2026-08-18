from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

import gate_cost_route_matrix as matrix


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _fingerprint(changed_files: list[str], tier: str) -> dict[str, object]:
    changed_entries = [
        {"path": path, "state": "file", "sha256": "b" * 64}
        for path in changed_files
    ]
    scope = {
        "schema": "kg.backlog.scope.v1",
        "files": [
            {"path": path, "operation": "add"}
            for path in changed_files
        ],
    }
    test_definition = {"files": []}
    fixtures = {"files": []}
    payload: dict[str, object] = {
        "schema": "kg.gate.cost-fingerprint.v1",
        "exact_head": "a" * 40,
        "head_sha": "a" * 40,
        "changed_files": changed_entries,
        "changed_file_digest": _digest(changed_entries),
        "acceptance_command": "uv run --no-project --python 3.13 --with pytest pytest -q",
        "acceptance_command_digest": _digest({
            "command": "uv run --no-project --python 3.13 --with pytest pytest -q",
        }),
        "test_definition": test_definition,
        "test_definition_digest": _digest(test_definition),
        "fixtures": fixtures,
        "fixture_digest": _digest(fixtures),
        "toolchain": {"python": "3.13"},
        "toolchain_version": "3.13",
        "scope": scope,
        "gate_tier": tier,
    }
    payload["fingerprint_digest"] = _digest(payload)
    return payload


@pytest.mark.parametrize(
    ("changed_files", "tier", "route_id"),
    [
        ([], "S0", "gate.s0.static"),
        (["docs/sop/backend.md"], "S0", "gate.s0.static"),
        (["ops/gate_cost_route_matrix.py"], "S1", "gate.s1.focused"),
        (["ios/BooksAndVocab/Views/ReaderView.swift"], "S2", "gate.s2.precise"),
        (["ios/BooksAndVocabUITests/ReaderFlowUITests.swift"], "S2", "gate.s2.precise"),
        (["backend/src/kg/api.py", "ops/test_timing.py"], "S3", "gate.s3.integration"),
        (["ops/test_ops.sh"], "S3", "gate.s3.integration"),
    ],
)
def test_changed_files_select_the_minimum_known_route(
    changed_files: list[str], tier: str, route_id: str,
) -> None:
    decision = matrix.route_changed_files(changed_files)

    assert decision["schema"] == "kg.gate.cost-route.v1"
    assert decision["changed_files"] == sorted(set(changed_files))
    assert decision["selected_tier"] == tier
    assert decision["route_id"] == route_id
    assert decision["fail_closed"] is False
    assert decision["fallback"] is False


def test_s4_is_only_selected_by_an_explicit_release_fingerprint() -> None:
    decision = matrix.route_fingerprint(
        _fingerprint(["ops/gate_cost_route_matrix.py"], "S4")
    )

    assert decision["selected_tier"] == "S4"
    assert decision["route_id"] == "gate.s4.release"
    assert decision["fingerprint"]["valid"] is True
    assert decision["fail_closed"] is False


def test_fingerprint_tier_cannot_understate_changed_file_requirement() -> None:
    decision = matrix.route(
        changed_files=["ios/BooksAndVocab/Views/ReaderView.swift"],
        fingerprint=_fingerprint(["ios/BooksAndVocab/Views/ReaderView.swift"], "S1"),
    )

    assert decision["fail_closed"] is True
    assert decision["fallback"] is True
    assert decision["selected_tier"] is None
    assert "fingerprint-tier-below-required" in decision["reasons"]


def test_unknown_surface_and_invalid_fingerprint_fail_closed() -> None:
    unknown_surface = matrix.route_changed_files(["future_surface/config.toml"])
    unknown_fixture = matrix.route_changed_files(["future_surface/fixtures/case.json"])
    invalid_fingerprint = matrix.route_fingerprint(
        {"schema": "unknown.schema.v9", "gate_tier": "S1"}
    )

    for decision in (unknown_surface, unknown_fixture, invalid_fingerprint):
        assert decision["fail_closed"] is True
        assert decision["fallback"] is True
        assert decision["selected_tier"] is None
        assert decision["route_id"] == "gate.unknown.fail-closed"


@pytest.mark.parametrize("field", ["head_sha", "fingerprint_digest", "scope"])
def test_fingerprint_identity_contradictions_fail_closed(field: str) -> None:
    fingerprint = _fingerprint(["ops/gate_cost_route_matrix.py"], "S1")
    if field == "head_sha":
        fingerprint["head_sha"] = "b" * 40
    elif field == "fingerprint_digest":
        fingerprint["fingerprint_digest"] = "2" * 64
    else:
        fingerprint["scope"] = {
            "schema": "kg.backlog.scope.v1",
            "files": [{"path": "ops/gate_cost_route_adapter.py", "operation": "add"}],
        }

    decision = matrix.route_fingerprint(fingerprint)

    assert decision["fail_closed"] is True
    assert decision["fallback"] is True
    assert decision["selected_tier"] is None
    assert decision["route_id"] == "gate.unknown.fail-closed"


def test_changed_files_and_fingerprint_must_describe_the_same_input() -> None:
    decision = matrix.route(
        changed_files=["ops/gate_cost_route_matrix.py"],
        fingerprint=_fingerprint(["ops/gate_cost_route_adapter.py"], "S1"),
    )

    assert decision["fail_closed"] is True
    assert "fingerprint-files-mismatch" in decision["reasons"]


def test_route_rejects_paths_that_escape_the_repository() -> None:
    with pytest.raises(matrix.RouteContractError, match="repository-relative"):
        matrix.route_changed_files(["../outside.py"])
