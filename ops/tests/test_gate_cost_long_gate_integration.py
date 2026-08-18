from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "ops" / "gate_cost_long_gate.py"


def test_cli_emits_machine_readable_contract_without_runner_connection() -> None:
    result = subprocess.run(
        [sys.executable, str(MODULE), "--json"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload["contract_ready"] is True
    assert payload["runner_connected"] is False
    assert payload["lane"]["independent"] is True
    assert payload["coalescing"]["same_fingerprint"] == "reuse"
    assert payload["coalescing"]["different_fingerprint"] == "parallel"
    assert payload["coalescing"]["stale"] == "fail-closed"
    assert payload["protected_gate_policy"] == {
        "coalesce": False,
        "defer": False,
        "degrade": False,
    }


def test_cli_plan_keeps_release_policy_strict_when_defer_and_degrade_are_requested() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(MODULE),
            "--json",
            "--fingerprint",
            "fp-release",
            "--gate-kind",
            "release",
            "--defer",
            "--degrade",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload["plan"]["decision"] == "run"
    assert payload["plan"]["protected_gate"] is True
    assert payload["plan"]["deferred"] is False
    assert payload["plan"]["degraded"] is False
