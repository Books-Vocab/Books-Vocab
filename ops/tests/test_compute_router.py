"""Focused routing contract for local/auto/felix compute execution."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.compute_router import choose_route, remote_failure

SAFETY_GATES = (
    ("live_admission", "no-live-admission"),
    ("probe_fresh", "probe-stale"),
    ("cross_host", "same-host"),
    ("production_healthy", "production-unhealthy"),
    ("receipt_key_pinned", "receipt-key-unpinned"),
    ("remote_eligible", "remote-ineligible"),
    ("source_clean", "dirty-source"),
    ("runner_verified", "runner-unverified"),
    ("sandbox_verified", "sandbox-unverified"),
)


def _safe(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "live_admission": True,
        "probe_fresh": True,
        "cross_host": True,
        "production_healthy": True,
        "receipt_key_pinned": True,
        "remote_eligible": True,
        "source_clean": True,
        "runner_verified": True,
        "sandbox_verified": True,
        "local_busy": True,
        "local_cost_ms": 1000,
        "felix_cost_ms": 400,
    }
    values.update(overrides)
    return values


def test_local_mode_is_deterministic_and_never_routes_remote() -> None:
    result = choose_route("local", **_safe())

    assert result == {
        "schema": "kg.compute.route.v1",
        "mode": "local",
        "selected": "local",
        "reason_code": "local-requested",
        "remote_started": False,
        "local_retry_allowed": False,
    }


def test_auto_selects_felix_only_when_busy_safe_and_profitable() -> None:
    selected = choose_route("auto", **_safe())
    assert selected["selected"] == "felix"
    assert selected["reason_code"] == "felix-selected-positive-savings"
    assert choose_route("auto", **_safe()) == selected


@pytest.mark.parametrize(("key", "suffix"), SAFETY_GATES)
def test_auto_fails_closed_to_local_on_every_safety_gate(key: str, suffix: str) -> None:
    result = choose_route("auto", **_safe(**{key: False}))
    assert result["selected"] == "local"
    assert result["reason_code"] == f"auto-local-{suffix}"


@pytest.mark.parametrize(("key", "suffix"), SAFETY_GATES)
def test_explicit_felix_cannot_bypass_any_safety_gate(key: str, suffix: str) -> None:
    result = choose_route("felix", **_safe(**{key: False}))
    assert result["selected"] is None
    assert result["reason_code"] == f"felix-refused-{suffix}"
    assert result["remote_started"] is False


def test_explicit_felix_ignores_busy_and_cost_but_not_safety() -> None:
    result = choose_route(
        "felix", **_safe(local_busy=False, local_cost_ms=None, felix_cost_ms=None)
    )
    assert result["selected"] == "felix"
    assert result["reason_code"] == "felix-requested-safe"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({"local_busy": False}, "auto-local-local-not-busy"),
        ({"local_busy": None}, "auto-local-local-load-unknown"),
        ({"local_cost_ms": None}, "auto-local-cost-unknown"),
        ({"felix_cost_ms": None}, "auto-local-cost-unknown"),
        (
            {"local_cost_ms": 400, "felix_cost_ms": 400},
            "auto-local-no-positive-savings",
        ),
    ),
)
def test_auto_unknown_busy_or_unprofitable_stays_local(
    overrides: dict[str, object], reason: str
) -> None:
    result = choose_route("auto", **_safe(**overrides))
    assert result["selected"] == "local"
    assert result["reason_code"] == reason


def test_non_boolean_facts_are_not_truthy_admission() -> None:
    result = choose_route("felix", **_safe(live_admission="yes"))
    assert result["selected"] is None
    assert result["reason_code"] == "felix-refused-no-live-admission"


def test_unknown_mode_and_bad_costs_are_rejected() -> None:
    with pytest.raises(ValueError):
        choose_route("ssh", **_safe())
    with pytest.raises(ValueError):
        choose_route("auto", **_safe(local_cost_ms=-1))
    with pytest.raises(ValueError):
        choose_route("auto", **_safe(felix_cost_ms=1.5))


def test_remote_failure_never_retries_locally_after_child_started() -> None:
    result = remote_failure("transport-ack-mismatch", child_started=True)

    assert result["selected"] == "felix"
    assert result["reason_code"] == "remote-failed-no-local-retry"
    assert result["remote_started"] is True
    assert result["local_retry_allowed"] is False
