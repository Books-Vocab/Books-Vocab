"""Decision-matrix tests for the compute router (pure, no I/O)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib.compute_router import RouterError, decide  # noqa: E402

NOW = 1_000_000.0


def _felix(**over):
    probe = {
        "reachable": True,
        "observed_at": NOW - 5,
        "host_id": "felix-host",
        "host_role": "felix",
        "admitted": True,
        "runner_verified": True,
        "sandbox_ok": True,
        "production_healthy": True,
        "receipt_key_pinned": True,
        "warmup_seconds": 5.0,
        "transfer_seconds": 5.0,
    }
    probe.update(over)
    return probe


def _local(**over):
    value = {
        "busy": True,
        "slowdown": 3.0,
        "missing_capabilities": [],
        "clean": True,
        "host_id": "oscar-host",
    }
    value.update(over)
    return value


def _decide(requested="auto", **over):
    args = dict(
        requested=requested,
        remote_eligible=True,
        minimum_remote_seconds=30,
        local=_local(),
        felix=_felix(),
        history=[100.0, 120.0, 110.0],
        now=NOW,
    )
    args.update(over)
    return decide(**args)


def test_auto_selects_felix_only_when_all_conditions_hold():
    result = _decide()
    assert result["target"] == "felix"
    assert result["reasons"] == ["remote-profitable"]
    assert result["net_savings_seconds"] == pytest.approx(110 * 3 - (110 + 10))


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"remote_eligible": False}, "remote-ineligible"),
        ({"felix": None}, "probe-unknown"),
        ({"felix": _felix(reachable=False)}, "felix-unreachable"),
        ({"felix": _felix(observed_at=NOW - 3600)}, "probe-stale"),
        ({"felix": _felix(host_id="oscar-host")}, "same-host"),
        ({"felix": _felix(host_role="oscar")}, "host-role"),
        ({"felix": _felix(admitted=False)}, "admission-denied"),
        ({"felix": _felix(runner_verified=False)}, "runner-unverified"),
        ({"felix": _felix(sandbox_ok=False)}, "sandbox-failed"),
        ({"felix": _felix(production_healthy=False)}, "production-unhealthy"),
        ({"felix": _felix(receipt_key_pinned=False)}, "receipt-key-unpinned"),
        ({"local": _local(clean=False)}, "dirty-source"),
        ({"local": _local(missing_capabilities=["uv"])}, "missing-capability"),
        ({"local": _local(busy=False)}, "local-not-busy"),
        ({"local": _local(busy=None)}, "local-load-unknown"),
        ({"local": _local(slowdown=None)}, "local-load-unknown"),
        ({"history": None}, "no-history"),
        ({"history": []}, "no-history"),
        ({"history": [10.0, 12.0]}, "below-minimum-remote-seconds"),
        ({"local": _local(slowdown=1.0)}, "not-profitable"),
        ({"felix": _felix(warmup_seconds=None)}, "probe-unknown"),
    ],
)
def test_auto_falls_back_to_local_with_reason(over, reason):
    result = _decide(**over)
    assert result["target"] == "local"
    assert reason in result["reasons"]


def test_auto_reason_codes_are_deterministic_and_sorted():
    over = {"felix": _felix(admitted=False, sandbox_ok=False), "history": None}
    result = _decide(**over)
    assert result["reasons"] == sorted(result["reasons"])
    assert result == _decide(**over)


def test_explicit_local_never_needs_remote_state():
    result = _decide("local", felix=None, remote_eligible=False)
    assert result == {
        "requested": "local",
        "target": "local",
        "reasons": ["explicit-local"],
        "net_savings_seconds": None,
    }


def test_explicit_felix_runs_even_when_not_profitable_or_local_idle():
    result = _decide("felix", local=_local(busy=False), history=None)
    assert result["target"] == "felix"
    assert result["reasons"] == ["explicit-felix"]


@pytest.mark.parametrize(
    "over",
    [
        {"remote_eligible": False},
        {"felix": None},
        {"felix": _felix(reachable=False)},
        {"felix": _felix(observed_at=NOW - 3600)},
        {"felix": _felix(host_id="oscar-host")},
        {"felix": _felix(admitted=False)},
        {"felix": _felix(runner_verified=False)},
        {"felix": _felix(sandbox_ok=False)},
        {"felix": _felix(production_healthy=False)},
        {"felix": _felix(receipt_key_pinned=False)},
        {"local": _local(clean=False)},
        {"local": _local(missing_capabilities=["uv"])},
    ],
)
def test_explicit_felix_cannot_bypass_safety_checks(over):
    with pytest.raises(RouterError) as caught:
        _decide("felix", **over)
    assert caught.value.reasons
    assert "explicit-felix" not in caught.value.reasons


def test_unknown_target_is_refused():
    with pytest.raises(RouterError):
        _decide("ssh")
