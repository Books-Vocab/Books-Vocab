from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

import gate_cost_long_gate as long_gate


def test_contract_is_ready_but_runner_wiring_is_explicitly_pending() -> None:
    contract = long_gate.build_long_gate_contract()

    assert contract["schema"] == long_gate.CONTRACT_SCHEMA
    assert contract["contract_ready"] is True
    assert contract["runner_connected"] is False
    assert contract["wiring_follow_up"] == {
        "owner": "manager",
        "next_step": "connect long-gate policy through the existing central runner after this ticket lands",
        "files": ["central-runner"],
    }


def test_contract_requires_observable_heartbeat_and_an_independent_resource_lane() -> None:
    contract = long_gate.build_long_gate_contract()

    assert contract["heartbeat"] == {
        "required": True,
        "interval_seconds": 20.0,
        "stale_after_seconds": 60.0,
        "observable": "stderr",
        "fields": [
            "elapsed",
            "pid",
            "alive",
            "stalled",
            "idle",
            "resource_key",
            "fingerprint",
        ],
    }
    assert contract["lane"] == {
        "name": "independent",
        "independent": True,
        "resource_key": long_gate.DEFAULT_RESOURCE_KEY,
        "different_fingerprints_may_run_in_parallel": True,
    }


def test_same_fingerprint_reuses_without_a_second_run() -> None:
    coordinator = long_gate.LongGateCoordinator()

    first = coordinator.request("fingerprint-a", now=100.0)
    second = coordinator.request("fingerprint-a", now=105.0)

    assert first["decision"] == "run"
    assert first["rerun"] is True
    assert second["decision"] == "reuse"
    assert second["rerun"] is False
    assert second["coalesced"] is True
    assert second["resource_key"] == long_gate.DEFAULT_RESOURCE_KEY


def test_heartbeat_refresh_keeps_the_same_fingerprint_reusable() -> None:
    coordinator = long_gate.LongGateCoordinator()

    coordinator.request("fingerprint-a", now=100.0)
    heartbeat = coordinator.heartbeat("fingerprint-a", at=150.0)
    reused = coordinator.request("fingerprint-a", now=200.0)

    assert heartbeat["heartbeat_at"] == 150.0
    assert heartbeat["phase"] == "heartbeat"
    assert reused["decision"] == "reuse"
    assert reused["stale"] is False


def test_different_fingerprints_share_the_lane_without_coalescing() -> None:
    coordinator = long_gate.LongGateCoordinator()

    first = coordinator.request("fingerprint-a", now=100.0)
    second = coordinator.request("fingerprint-b", now=100.0)

    assert first["decision"] == "run"
    assert second["decision"] == "run"
    assert second["coalesced"] is False
    assert second["parallel_allowed"] is True
    assert second["resource_key"] == first["resource_key"]
    assert coordinator.active_fingerprints() == ["fingerprint-a", "fingerprint-b"]


def test_direct_plan_does_not_reuse_a_different_fingerprint_state() -> None:
    result = long_gate.plan_long_gate(
        "fingerprint-b",
        existing={
            "fingerprint": "fingerprint-a",
            "status": "running",
            "heartbeat_at": 100.0,
        },
        now=105.0,
    )

    assert result["decision"] == "run"
    assert result["reason"] == "different-fingerprint"
    assert result["parallel_allowed"] is True


def test_stale_heartbeat_fails_closed_instead_of_reusing_or_rerunning() -> None:
    coordinator = long_gate.LongGateCoordinator()

    coordinator.request("fingerprint-a", now=100.0)
    stale = coordinator.request("fingerprint-a", now=160.1)

    assert stale["decision"] == "fail-closed"
    assert stale["reason"] == "stale-heartbeat"
    assert stale["rerun"] is False
    assert stale["coalesced"] is False
    assert stale["stale"] is True


@pytest.mark.parametrize("gate_kind", ["release", "full", "S4"])
def test_release_and_full_gates_never_coalesce_defer_or_degrade(
    gate_kind: str,
) -> None:
    coordinator = long_gate.LongGateCoordinator()

    first = coordinator.request(
        "fingerprint-a",
        gate_kind=gate_kind,
        now=100.0,
        defer=True,
        degrade=True,
    )
    second = coordinator.request(
        "fingerprint-a",
        gate_kind=gate_kind,
        now=101.0,
        defer=True,
        degrade=True,
    )

    for result in (first, second):
        assert result["decision"] == "run"
        assert result["protected_gate"] is True
        assert result["coalesced"] is False
        assert result["deferred"] is False
        assert result["degraded"] is False
    assert second["rerun"] is True


def test_missing_heartbeat_is_stale_for_an_external_state() -> None:
    result = long_gate.plan_long_gate(
        "fingerprint-a",
        existing={"status": "running", "heartbeat_at": None},
        now=100.0,
    )

    assert result["decision"] == "fail-closed"
    assert result["reason"] == "stale-heartbeat"
