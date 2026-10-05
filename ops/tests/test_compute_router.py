"""Focused routing contract for local/auto/felix compute execution."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.compute_router import choose_route, remote_failure


def _safe(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "live_admission": True,
        "remote_eligible": True,
        "source_clean": True,
        "runner_verified": True,
        "sandbox_verified": True,
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


def test_auto_requires_every_felix_gate_and_positive_savings() -> None:
    selected = choose_route("auto", **_safe())
    assert selected["selected"] == "felix"
    assert selected["reason_code"] == "felix-selected-positive-savings"

    for key, value, reason in (
        ("live_admission", False, "auto-local-no-live-admission"),
        ("remote_eligible", False, "auto-local-remote-ineligible"),
        ("source_clean", False, "auto-local-dirty-source"),
        ("runner_verified", False, "auto-local-runner-unverified"),
        ("sandbox_verified", False, "auto-local-sandbox-unverified"),
    ):
        result = choose_route("auto", **_safe(**{key: value}))
        assert result["selected"] == "local"
        assert result["reason_code"] == reason

    no_savings = choose_route("auto", **_safe(local_cost_ms=400, felix_cost_ms=400))
    assert no_savings["selected"] == "local"
    assert no_savings["reason_code"] == "auto-local-no-positive-savings"


def test_explicit_felix_does_not_bypass_safety() -> None:
    refused = choose_route("felix", **_safe(source_clean=False))

    assert refused["selected"] is None
    assert refused["reason_code"] == "felix-refused-dirty-source"
    assert refused["remote_started"] is False


def test_remote_failure_never_retries_locally_after_child_started() -> None:
    result = remote_failure("transport-ack-mismatch", child_started=True)

    assert result["selected"] == "felix"
    assert result["reason_code"] == "remote-failed-no-local-retry"
    assert result["remote_started"] is True
    assert result["local_retry_allowed"] is False
