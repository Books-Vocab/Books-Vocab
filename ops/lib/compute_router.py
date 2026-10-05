"""Deterministic local/auto/Felix routing for bounded compute profiles.

This module is deliberately observation-driven.  It does not discover hosts,
start agents, or retry work.  Callers must provide the current admission and
provenance facts before a remote route can be selected.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "kg.compute.route.v1"
MODES = frozenset({"local", "auto", "felix"})


def _local(mode: str, reason_code: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": mode,
        "selected": "local",
        "reason_code": reason_code,
        "remote_started": False,
        "local_retry_allowed": False,
    }


def _refused(mode: str, reason_code: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": mode,
        "selected": None,
        "reason_code": reason_code,
        "remote_started": False,
        "local_retry_allowed": False,
    }


def choose_route(
    mode: str,
    *,
    live_admission: bool,
    remote_eligible: bool,
    source_clean: bool,
    runner_verified: bool,
    sandbox_verified: bool,
    local_cost_ms: int,
    felix_cost_ms: int,
) -> dict[str, Any]:
    """Return a stable route decision from explicit, already-read facts."""

    if mode not in MODES:
        raise ValueError(f"unsupported compute mode: {mode}")
    if not isinstance(local_cost_ms, int) or not isinstance(felix_cost_ms, int):
        raise ValueError("cost estimates must be integers")
    if local_cost_ms < 0 or felix_cost_ms < 0:
        raise ValueError("cost estimates must be non-negative")
    if mode == "local":
        return _local(mode, "local-requested")

    gates = (
        (not live_admission, "no-live-admission"),
        (not remote_eligible, "remote-ineligible"),
        (not source_clean, "dirty-source"),
        (not runner_verified, "runner-unverified"),
        (not sandbox_verified, "sandbox-unverified"),
    )
    for failed, suffix in gates:
        if failed:
            return (
                _local("auto", f"auto-local-{suffix}")
                if mode == "auto"
                else _refused("felix", f"felix-refused-{suffix}")
            )

    if mode == "auto" and felix_cost_ms >= local_cost_ms:
        return _local(mode, "auto-local-no-positive-savings")
    return {
        "schema": SCHEMA,
        "mode": mode,
        "selected": "felix",
        "reason_code": "felix-selected-positive-savings" if mode == "auto" else "felix-requested-safe",
        "remote_started": False,
        "local_retry_allowed": False,
    }


def remote_failure(reason_code: str, *, child_started: bool) -> dict[str, Any]:
    """Classify a remote failure without creating an implicit local retry."""

    return {
        "schema": SCHEMA,
        "mode": "felix",
        "selected": "felix" if child_started else None,
        "reason_code": "remote-failed-no-local-retry" if child_started else reason_code,
        "remote_started": child_started,
        "local_retry_allowed": False,
    }
