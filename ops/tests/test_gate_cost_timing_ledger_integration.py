from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "ops" / "gate_cost_timing_ledger.py"


def _record(kind: str, index: int) -> dict[str, object]:
    return {
        "duration_s": float(index + len(kind)),
        "rc": 0,
        "verdict": "reused" if kind == "reuse_verdict" and index % 2 else "pass",
        "fingerprint": f"fp-{kind}-{index}",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "lease_wait_s": 0.25,
    }


def _ledger() -> dict[str, object]:
    kinds = ("packet", "full_gate", "precise_gate", "reuse_verdict")
    return {
        "schema": "kg.gate.timing-ledger.v1",
        "version": 1,
        "contract_ready": True,
        "runner_connected": False,
        "runner_consumed": False,
        "wiring_follow_up": {
            "owner": "manager",
            "next_step": "connect timing ledger consumption through the existing central runner after this ticket lands",
            "files": ["central-runner"],
        },
        "waves": [
            {
                "wave_id": f"wave-{index:02d}",
                **{kind: _record(kind, index) for kind in kinds},
            }
            for index in range(1, 11)
        ],
    }


def _run(*args: str, input_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MODULE), *args, "--input", str(input_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_validate_is_machine_readable_and_keeps_runner_disconnected(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ledger.json"
    source.write_text(json.dumps(_ledger()), encoding="utf-8")

    completed = _run("validate", input_path=source)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema"] == "kg.gate.timing-ledger.validation.v1"
    assert payload["valid"] is True
    assert payload["contract_ready"] is True
    assert payload["runner_connected"] is False
    assert payload["runner_consumed"] is False


def test_cli_summarize_reports_only_supplied_waves(tmp_path: Path) -> None:
    source = tmp_path / "ledger.json"
    source.write_text(json.dumps(_ledger()), encoding="utf-8")

    completed = _run("summarize", input_path=source)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema"] == "kg.gate.timing-ledger.summary.v1"
    assert payload["wave_count"] == 10
    assert payload["measurements"]["full_gate"]["count"] == 10
    assert payload["historical_data"] is True


def test_cli_schema_does_not_create_fake_wave_history() -> None:
    completed = subprocess.run(
        [sys.executable, str(MODULE), "schema"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema"] == "kg.gate.timing-ledger.v1"
    assert payload["contract_ready"] is True
    assert payload["waves"] == []
    assert payload["historical_data"] is False


def test_cli_invalid_wave_window_returns_json_failure(tmp_path: Path) -> None:
    source = tmp_path / "ledger.json"
    payload = _ledger()
    payload["waves"] = payload["waves"][:9]
    source.write_text(json.dumps(payload), encoding="utf-8")

    completed = _run("validate", input_path=source)

    assert completed.returncode != 0
    result = json.loads(completed.stdout)
    assert result["valid"] is False
    assert any("10" in error and "20" in error for error in result["errors"])
