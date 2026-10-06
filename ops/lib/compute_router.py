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


def _cost_ok(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def choose_route(
    mode: str,
    *,
    live_admission: bool,
    probe_fresh: bool,
    cross_host: bool,
    production_healthy: bool,
    receipt_key_pinned: bool,
    remote_eligible: bool,
    source_clean: bool,
    runner_verified: bool,
    sandbox_verified: bool,
    local_busy: bool | None,
    local_cost_ms: int | None,
    felix_cost_ms: int | None,
) -> dict[str, Any]:
    """Return a stable route decision from explicit, already-read facts.

    Only the literal ``True`` satisfies a safety fact, so unknown or malformed
    observations fail closed.  Explicit ``felix`` shares every safety gate with
    ``auto``; only the busy/cost economics are auto-only.
    """

    if mode not in MODES:
        raise ValueError(f"unsupported compute mode: {mode}")
    for cost in (local_cost_ms, felix_cost_ms):
        if cost is not None and not _cost_ok(cost):
            raise ValueError("cost estimates must be non-negative integers or None")
    if mode == "local":
        return _local(mode, "local-requested")

    gates = (
        (live_admission is not True, "no-live-admission"),
        (probe_fresh is not True, "probe-stale"),
        (cross_host is not True, "same-host"),
        (production_healthy is not True, "production-unhealthy"),
        (receipt_key_pinned is not True, "receipt-key-unpinned"),
        (remote_eligible is not True, "remote-ineligible"),
        (source_clean is not True, "dirty-source"),
        (runner_verified is not True, "runner-unverified"),
        (sandbox_verified is not True, "sandbox-unverified"),
    )
    for failed, suffix in gates:
        if failed:
            return (
                _local("auto", f"auto-local-{suffix}")
                if mode == "auto"
                else _refused("felix", f"felix-refused-{suffix}")
            )

    if mode == "auto":
        if local_busy is False:
            return _local(mode, "auto-local-local-not-busy")
        if local_busy is not True:
            return _local(mode, "auto-local-local-load-unknown")
        if local_cost_ms is None or felix_cost_ms is None:
            return _local(mode, "auto-local-cost-unknown")
        if felix_cost_ms >= local_cost_ms:
            return _local(mode, "auto-local-no-positive-savings")
    return {
        "schema": SCHEMA,
        "mode": mode,
        "selected": "felix",
        "reason_code": "felix-selected-positive-savings"
        if mode == "auto"
        else "felix-requested-safe",
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
