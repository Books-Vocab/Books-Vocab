from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

import gate_cost_route_adapter as adapter


def test_standalone_adapter_is_contract_ready_but_not_runner_connected() -> None:
    payload = adapter.build_adapter_output(
        changed_files=["ops/gate_cost_route_matrix.py"],
    )

    assert payload["schema"] == "kg.gate.cost.route-adapter.v1"
    assert payload["contract_ready"] is True
    assert payload["runner_connected"] is False
    assert payload["integration"]["contract_ready"] is True
    assert payload["integration"]["runner_connected"] is False
    assert payload["wiring_follow_up"] == {
        "owner": "manager",
        "next_step": "connect adapter through the existing planner and Manager gate after this ticket lands",
        "files": ["ops/test_ops.sh"],
    }
    assert payload["planner_input"] == {
        "changed_files": ["ops/gate_cost_route_matrix.py"],
        "gate_tier": "S1",
        "route_id": "gate.s1.focused",
        "fallback": False,
    }


def test_runner_connected_requires_explicit_verified_central_runner_evidence() -> None:
    payload = adapter.build_adapter_output(
        changed_files=["ops/gate_cost_route_matrix.py"],
        runner_evidence={
            "runner": "ops/test_ops.sh",
            "connected": True,
        },
    )

    assert payload["contract_ready"] is True
    assert payload["runner_connected"] is False

    connected = adapter.build_adapter_output(
        changed_files=["ops/gate_cost_route_matrix.py"],
        runner_evidence={
            "schema": "kg.gate.runner-connection.v1",
            "runner": "ops/test_ops.sh",
            "connected": True,
            "verified": True,
            "source": "central-runner",
        },
    )
    assert connected["runner_connected"] is True
    assert connected["wiring_follow_up"] is None


def test_unknown_route_keeps_contract_evidence_separate_from_execution() -> None:
    payload = adapter.build_adapter_output(
        changed_files=["future_surface/config.toml"],
    )

    assert payload["contract_ready"] is True
    assert payload["runner_connected"] is False
    assert payload["routing"]["fail_closed"] is True
    assert payload["planner_input"]["gate_tier"] is None


def test_adapter_json_is_stable_and_contains_no_raw_runner_claim() -> None:
    first = adapter.dumps_adapter_output(
        changed_files=["ops/gate_cost_route_matrix.py"],
    )
    second = adapter.dumps_adapter_output(
        changed_files=["ops/gate_cost_route_matrix.py"],
    )

    assert first == second
    decoded = json.loads(first)
    assert decoded["contract_ready"] is True
    assert decoded["runner_connected"] is False
    assert "ops/test_ops.sh" in decoded["wiring_follow_up"]["files"]
