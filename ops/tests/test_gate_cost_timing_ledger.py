from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

import gate_cost_timing_ledger as ledger

MEASUREMENT_KINDS = ("packet", "full_gate", "precise_gate", "reuse_verdict")


def _measurement(kind: str, index: int, *, verdict: str = "pass") -> dict[str, object]:
    return {
        "duration_s": float(index + len(kind)),
        "rc": 0,
        "verdict": verdict,
        "fingerprint": f"fp-{kind}-{index}",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "lease_wait_s": float(index) / 10,
    }


def _waves(count: int = 10) -> list[dict[str, object]]:
    return [
        {
            "wave_id": f"wave-{index:02d}",
            **{
                kind: _measurement(
                    kind,
                    index,
                    verdict="reused"
                    if kind == "reuse_verdict" and index % 2
                    else "pass",
                )
                for kind in MEASUREMENT_KINDS
            },
        }
        for index in range(1, count + 1)
    ]


def test_build_ledger_emits_contract_and_preserves_all_four_measurements() -> None:
    result = ledger.build_ledger(
        waves=_waves(),
        ticket="IMP-20260818-7807cd",
        packet="p3-paired-timing",
    )

    assert result["schema"] == "kg.gate.timing-ledger.v1"
    assert result["version"] == 1
    assert result["contract_ready"] is True
    assert result["runner_connected"] is False
    assert result["runner_consumed"] is False
    assert result["wiring_follow_up"]["owner"] == "manager"
    assert result["wave_count"] == 10
    assert result["ticket"] == "IMP-20260818-7807cd"
    assert result["packet"] == "p3-paired-timing"

    first = result["waves"][0]
    assert set(MEASUREMENT_KINDS) <= first.keys()
    for kind in MEASUREMENT_KINDS:
        expected_verdict = "reused" if kind == "reuse_verdict" else "pass"
        assert first[kind] == _measurement(kind, 1, verdict=expected_verdict)


@pytest.mark.parametrize("count", [0, 1, 9, 21])
def test_ledger_requires_a_real_10_to_20_wave_window(count: int) -> None:
    with pytest.raises(ledger.LedgerContractError, match="10.*20"):
        ledger.build_ledger(waves=_waves(count))


def test_validator_rejects_missing_measurement_and_does_not_fill_history() -> None:
    waves = _waves()
    del waves[0]["full_gate"]

    result = ledger.validate_ledger(
        {
            "schema": "kg.gate.timing-ledger.v1",
            "version": 1,
            "contract_ready": True,
            "runner_connected": False,
            "runner_consumed": False,
            "wiring_follow_up": ledger.DEFAULT_WIRING_FOLLOW_UP,
            "waves": waves,
        }
    )

    assert result["valid"] is False
    assert any("full_gate" in error for error in result["errors"])


def test_validator_rejects_mismatched_head_base_and_invalid_duration() -> None:
    waves = _waves()
    waves[1]["precise_gate"]["head_sha"] = "c" * 40
    waves[2]["packet"]["duration_s"] = -0.1

    result = ledger.validate_ledger(ledger.build_ledger(waves=_waves()))
    assert result["valid"] is True

    invalid = ledger.build_ledger(waves=_waves())
    invalid["waves"][1]["precise_gate"]["head_sha"] = "c" * 40
    invalid["waves"][2]["packet"]["duration_s"] = -0.1
    result = ledger.validate_ledger(invalid)

    assert result["valid"] is False
    assert any("head_sha" in error for error in result["errors"])
    assert any("duration_s" in error for error in result["errors"])


def test_summarizer_reports_observed_costs_without_runner_claims() -> None:
    result = ledger.summarize_ledger(
        ledger.build_ledger(waves=_waves(), runner_connected=False)
    )

    assert result["schema"] == "kg.gate.timing-ledger.summary.v1"
    assert result["source_schema"] == "kg.gate.timing-ledger.v1"
    assert result["contract_ready"] is True
    assert result["runner_connected"] is False
    assert result["runner_consumed"] is False
    assert result["wave_count"] == 10
    assert result["measurements"]["packet"]["count"] == 10
    assert result["measurements"]["packet"]["duration_s"]["total"] == pytest.approx(
        115.0
    )
    assert result["measurements"]["reuse_verdict"]["verdict_counts"] == {
        "pass": 5,
        "reused": 5,
    }


def test_runner_connection_requires_explicit_evidence() -> None:
    with pytest.raises(ledger.LedgerContractError, match="runner evidence"):
        ledger.build_ledger(waves=_waves(), runner_connected=True)

    result = ledger.build_ledger(
        waves=_waves(),
        runner_connected=True,
        runner_evidence={
            "source": "central-runner",
            "evidence": {"receipt": "manager-supplied runner receipt"},
        },
    )
    assert result["runner_connected"] is True
    assert result["runner_consumed"] is True
    assert result["runner_state"]["source"] == "central-runner"


def test_empty_contract_is_explicitly_not_a_historical_ledger() -> None:
    result = ledger.new_contract()

    assert result["schema"] == "kg.gate.timing-ledger.v1"
    assert result["contract_ready"] is True
    assert result["waves"] == []
    assert result["wave_count"] == 0
    assert result["historical_data"] is False
