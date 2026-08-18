from __future__ import annotations

import json
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

import test_timing
from lib import gate_cost_measurement as measurement


def test_timing_contract_records_execution_identity_and_cost() -> None:
    record = measurement.build_timing_contract(
        head_sha="a" * 40,
        changed_files=["./ops/test_timing.py", "ops/test_timing.py", "docs/ops.md"],
        ticket="IMP-20260818-timing",
        packet="packet-7",
        gate_tier="s1",
        command="ops.gate-cost.test",
        duration_s=12.3456,
        simulator_lease_wait_s=0.75,
        cache_status="hit",
    )

    assert record == {
        "schema": "kg.test.timing.contract.v1",
        "version": 1,
        "head_sha": "a" * 40,
        "changed_files": ["docs/ops.md", "ops/test_timing.py"],
        "ticket": "IMP-20260818-timing",
        "packet": "packet-7",
        "gate_tier": "S1",
        "minimum_acceptance_tier": "S1",
        "required_cutover_tier": "S2",
        "route_schema": "kg.test.impact.route.v1",
        "route_id": "impact.unit-ops",
        "acceptance_route": "unit-ops",
        "command": "ops.gate-cost.test",
        "duration_s": 12.346,
        "simulator_lease_wait_s": 0.75,
        "cache_status": "hit",
        "tier_compliant": True,
    }


@pytest.mark.parametrize(
    ("changed_files", "tier", "route"),
    [
        ([], "S0", "static"),
        (["README.md", "docs/sop/backend.md"], "S0", "static"),
        (["ops/test_timing.py", "ops/tests/test_gate_cost_measurement.py"], "S1", "unit-ops"),
        (["ios/BooksAndVocab/Models/ReaderModel.swift"], "S1", "unit-ops"),
        (["ios/BooksAndVocab/Views/ReaderView.swift"], "S2", "ui-precise"),
        (["backend/src/kg/api.py", "ops/test_timing.py"], "S3", "full-gate"),
        (["ops/worktree_orchestrate.py"], "S3", "full-gate"),
        (["ops/tests/fixtures/shared.json"], "S3", "full-gate"),
    ],
)
def test_changed_files_choose_minimum_acceptance_route(
    changed_files: list[str], tier: str, route: str,
) -> None:
    decision = measurement.minimum_acceptance_route(changed_files)

    assert decision["schema"] == "kg.test.impact.v1"
    assert decision["changed_files"] == sorted(set(changed_files))
    assert decision["minimum_acceptance_tier"] == tier
    assert decision["acceptance_route"] == route
    assert decision["route_id"] == f"impact.{route}"


def test_cross_surface_and_control_plane_changes_explain_s3_escalation() -> None:
    cross_surface = measurement.minimum_acceptance_route(
        ["ios/BooksAndVocab/Views/ReaderView.swift", "ops/test_timing.py"]
    )
    control_plane = measurement.minimum_acceptance_route(["ops/worktree_orchestrate.py"])

    assert "cross-functional-surface" in cross_surface["escalation_reasons"]
    assert "control-plane" in control_plane["escalation_reasons"]


def test_timing_contract_rejects_invalid_cost_and_cache_values() -> None:
    with pytest.raises(measurement.MeasurementContractError, match="duration_s"):
        measurement.build_timing_contract(
            head_sha="a" * 40,
            changed_files=[],
            gate_tier="S0",
            command="ops.test",
            duration_s=-1,
            simulator_lease_wait_s=0,
            cache_status="miss",
        )

    with pytest.raises(measurement.MeasurementContractError, match="cache_status"):
        measurement.build_timing_contract(
            head_sha="a" * 40,
            changed_files=[],
            gate_tier="S0",
            command="ops.test",
            duration_s=1,
            simulator_lease_wait_s=0,
            cache_status="maybe",
        )


def test_timing_contract_never_persists_raw_argv_or_false_green_tier() -> None:
    with pytest.raises(measurement.MeasurementContractError, match="raw argv"):
        measurement.build_timing_contract(
            head_sha="a" * 40,
            changed_files=["ops/test_timing.py"],
            gate_tier="S1",
            command=["uv", "run", "pytest", "--secret", "token"],
            duration_s=1,
        )

    record = measurement.build_timing_contract(
        head_sha="a" * 40,
        changed_files=["ops/test_timing.py"],
        command="ops.test",
        duration_s=1,
    )

    assert record["gate_tier"] is None
    assert record["tier_compliant"] is False

    empty_tier = measurement.build_timing_contract(
        head_sha="a" * 40,
        changed_files=["ops/test_timing.py"],
        gate_tier="",
        command="ops.test",
        duration_s=1,
    )

    assert empty_tier["gate_tier"] is None
    assert empty_tier["tier_compliant"] is False


def test_unknown_surface_is_conservatively_full_gate() -> None:
    decision = measurement.minimum_acceptance_route(["new_product_surface/config.toml"])

    assert decision["minimum_acceptance_tier"] == "S3"
    assert decision["acceptance_route"] == "full-gate"
    assert "unknown-surface" in decision["escalation_reasons"]


def test_design_system_and_path_validation_are_explicit() -> None:
    design_system = measurement.minimum_acceptance_route(["design-system/tokens.json"])

    assert design_system["minimum_acceptance_tier"] == "S2"
    assert design_system["acceptance_route"] == "ui-precise"

    with pytest.raises(measurement.MeasurementContractError, match="repository-relative"):
        measurement.minimum_acceptance_route(["../outside-repository.txt"])


def test_bundle_status_contains_one_timing_contract_per_task(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("KG_TEST_TIMING_DB", str(tmp_path / "timing.sqlite3"))
    manifest = tmp_path / "bundle.json"
    manifest.write_text(json.dumps({
        "schema": "kg.test.bundle.v1",
        "bundle_id": "gate-cost-test",
        "head_sha": "b" * 40,
        "changed_files": ["ops/test_timing.py"],
        "ticket": "IMP-20260818-timing",
        "packet": "packet-7",
        "gate_tier": "s1",
        "tasks": [{
            "id": "timed-task",
            "command_key": "ops.gate-cost.test",
            "command": [sys.executable, "-c", "pass"],
            "resource_class": "simulator",
            "cache_status": "warm",
        }],
    }))

    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-contract", json=True)
    assert test_timing.cmd_run_bundle(args) == 0
    payload = json.loads(capsys.readouterr().out)
    row = payload["tasks"][0]
    contract = row["timing_contract"]

    assert contract["schema"] == "kg.test.timing.contract.v1"
    assert contract["head_sha"] == "b" * 40
    assert contract["changed_files"] == ["ops/test_timing.py"]
    assert contract["ticket"] == "IMP-20260818-timing"
    assert contract["packet"] == "packet-7"
    assert contract["gate_tier"] == "S1"
    assert contract["command"] == "ops.gate-cost.test"
    assert contract["duration_s"] >= 0
    assert contract["simulator_lease_wait_s"] >= 0
    assert contract["cache_status"] == "hit"
    assert payload["timing_contract"]["records"] == [contract]

    with sqlite3.connect(tmp_path / "timing.sqlite3") as connection:
        stored = connection.execute(
            "SELECT tier, cache_status FROM measurements WHERE measurement_scope = 'command'"
        ).fetchone()
    assert stored == ("S1", "hit")


def test_bundle_rejects_invalid_timing_metadata_before_command(tmp_path, capsys) -> None:
    marker = tmp_path / "must-not-run"
    manifest = tmp_path / "invalid-metadata.json"
    manifest.write_text(json.dumps({
        "schema": "kg.test.bundle.v1",
        "bundle_id": "invalid-metadata",
        "gate_tier": "S9",
        "tasks": [{
            "id": "invalid-task",
            "command_key": "ops.invalid-metadata",
            "command": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        }],
    }))

    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-invalid", json=True)
    assert test_timing.cmd_run_bundle(args) == 1
    payload = json.loads(capsys.readouterr().out)
    row = payload["tasks"][0]

    assert row["status"] == "error"
    assert "timing metadata rejected" in row["error"]
    assert not marker.exists()
