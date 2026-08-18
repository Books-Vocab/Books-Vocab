from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate_cost_reuse as reuse


def test_standalone_contract_round_trips_as_machine_readable_json() -> None:
    identity = reuse.build_reuse_identity(
        head="a" * 40,
        base="b" * 40,
        changed_files=["ops/gate_cost_reuse.py"],
        command="pytest -q ops/tests/test_gate_cost_reuse.py",
        test_definition={"files": ["ops/tests/test_gate_cost_reuse.py"]},
        fixture={"files": []},
        toolchain={"python": "3.13.7"},
        scope={"files": [{"path": "ops/gate_cost_reuse.py", "operation": "add"}]},
        tier="S1",
        issued_at="2026-08-18T14:00:00Z",
        expires_at="2026-08-18T15:00:00Z",
    )

    payload = reuse.evaluate_reuse(
        reuse.build_reuse_verdict(identity, verdict="pass"),
        identity,
        now=datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc),
    )
    decoded = json.loads(reuse.dumps(payload))

    assert decoded["schema"] == reuse.VERDICT_SCHEMA
    assert decoded["reuse"] is True
    assert decoded["contract_ready"] is True
    assert decoded["runner_connected"] is False


def test_standalone_module_does_not_wire_existing_runner_surfaces() -> None:
    source = Path(reuse.__file__).read_text(encoding="utf-8")

    assert "gate_cost_fingerprint" not in source
    assert "gate_cost_execution_plan" not in source
    assert "worktree_orchestrator_core_gate_execution" not in source
