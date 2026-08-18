"""Pure contracts for gate timing evidence and changed-file impact routing.

This module intentionally has no filesystem, git, subprocess, or environment
access.  It turns caller-supplied execution facts into stable JSON-shaped
records and chooses the cheapest honest acceptance route for a changed-file
set.  Runners own measurement; this module owns only normalization and policy.
"""

from __future__ import annotations

import math
import posixpath
from collections.abc import Iterable, Sequence
from typing import Any


TIMING_CONTRACT_SCHEMA = "kg.test.timing.contract.v1"
IMPACT_SCHEMA = "kg.test.impact.v1"
CONTRACT_VERSION = 1
GATE_TIERS = ("S0", "S1", "S2", "S3", "S4")
_TIER_RANK = {tier: rank for rank, tier in enumerate(GATE_TIERS)}
_CACHE_ALIASES = {
    "warm": "hit",
    "cold": "miss",
    "n/a": "not-applicable",
    "na": "not-applicable",
}
CACHE_STATUSES = frozenset({"hit", "miss", "stale", "unknown", "not-applicable"})
_FUNCTIONAL_ROOTS = frozenset({"backend", "ios", "lab", "ops", "design-system"})
_CONTROL_PLANE_EXACT = frozenset({
    "ops/worktree_orchestrate.py",
    "ops/ios_test.sh",
    "ops/test_ops.sh",
})


class MeasurementContractError(ValueError):
    """A timing or impact payload cannot satisfy its machine contract."""


def _normalize_changed_files(changed_files: Iterable[str] | None) -> list[str]:
    if changed_files is None:
        return []
    if isinstance(changed_files, (str, bytes)):
        raise MeasurementContractError("changed_files must be an iterable of paths")
    normalized: set[str] = set()
    for raw_path in changed_files:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise MeasurementContractError("changed_files must contain non-empty strings")
        path = raw_path.strip().replace("\\", "/")
        path = posixpath.normpath(path)
        if path in {"", "."} or path.startswith("/") or path == ".." or path.startswith("../"):
            raise MeasurementContractError(f"changed file path must be repository-relative: {raw_path!r}")
        normalized.add(path.removeprefix("./"))
    return sorted(normalized)


def _normalize_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        if not command.strip():
            raise MeasurementContractError("command must not be empty")
        return [command]
    if isinstance(command, (bytes, bytearray)) or not isinstance(command, Sequence):
        raise MeasurementContractError("command must be a string or sequence of strings")
    result = list(command)
    if not result or any(not isinstance(value, str) or not value for value in result):
        raise MeasurementContractError("command must contain at least one non-empty string")
    return result


def _normalize_optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MeasurementContractError(f"{field} must be a non-empty string or null")
    return value.strip()


def normalize_gate_tier(value: str) -> str:
    candidate = str(value).upper()
    if candidate not in _TIER_RANK:
        raise MeasurementContractError(
            f"gate_tier must be one of {', '.join(GATE_TIERS)}; got {value!r}"
        )
    return candidate


def normalize_cache_status(value: str | None) -> str:
    candidate = "unknown" if value is None else str(value).strip().lower()
    candidate = _CACHE_ALIASES.get(candidate, candidate)
    if candidate not in CACHE_STATUSES:
        allowed = ", ".join(sorted(CACHE_STATUSES))
        raise MeasurementContractError(
            f"cache_status must be one of {allowed}; got {value!r}"
        )
    return candidate


def _non_negative_finite(value: float | int, field: str) -> float:
    if isinstance(value, bool):
        raise MeasurementContractError(f"{field} must be a finite non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MeasurementContractError(f"{field} must be a finite non-negative number") from exc
    if not math.isfinite(number) or number < 0:
        raise MeasurementContractError(f"{field} must be a finite non-negative number")
    return number


def _is_shared_fixture(path: str) -> bool:
    parts = path.lower().split("/")
    basename = parts[-1]
    return (
        "fixtures" in parts
        or "fixture" in parts
        or "fixture" in basename
        or "snapshot" in basename
    )


def _is_control_plane(path: str) -> bool:
    if path in _CONTROL_PLANE_EXACT:
        return True
    return (
        path.startswith("ops/lib/worktree_orchestrator_")
        or path.startswith("ops/worktree_registry.py")
        or path.startswith("ops/context_route.py")
        or path.startswith("ops/skill_route.py")
    )


def _is_ui_surface(path: str) -> bool:
    return path.startswith("ios/")


def minimum_acceptance_route(changed_files: Iterable[str] | None) -> dict[str, Any]:
    """Choose the minimum honest acceptance route for repository-relative paths.

    The route is deliberately conservative at the boundaries:

    * S0/static: documentation and neutral metadata only;
    * S1/unit-ops: one functional non-UI surface with focused unit/ops checks;
    * S2/ui-precise: an iOS/UI surface with a precise UI route;
    * S3/full-gate: cross-functional, control-plane, or shared-fixture changes.

    S4 remains an explicit release decision and is never inferred from a file
    path.  The return value is JSON-serializable and contains no live state.
    """
    paths = _normalize_changed_files(changed_files)
    functional_roots = sorted({path.split("/", 1)[0] for path in paths} & _FUNCTIONAL_ROOTS)
    control_plane = sorted(path for path in paths if _is_control_plane(path))
    shared_fixtures = sorted(path for path in paths if _is_shared_fixture(path))
    ui_files = sorted(path for path in paths if _is_ui_surface(path))

    reasons: list[str] = []
    if len(functional_roots) >= 2:
        reasons.append("cross-functional-surface")
    if control_plane:
        reasons.append("control-plane")
    if shared_fixtures:
        reasons.append("shared-fixture")

    if reasons:
        minimum_tier, acceptance_route = "S3", "full-gate"
    elif ui_files:
        minimum_tier, acceptance_route = "S2", "ui-precise"
    elif functional_roots:
        minimum_tier, acceptance_route = "S1", "unit-ops"
    else:
        minimum_tier, acceptance_route = "S0", "static"

    return {
        "schema": IMPACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "changed_files": paths,
        "minimum_gate_tier": minimum_tier,
        "acceptance_route": acceptance_route,
        "escalation_reasons": sorted(reasons),
    }


def build_timing_contract(
    *,
    head_sha: str | None,
    changed_files: Iterable[str] | None,
    command: str | Sequence[str],
    duration_s: float | int,
    simulator_lease_wait_s: float | int = 0.0,
    cache_status: str | None = None,
    ticket: str | None = None,
    packet: str | None = None,
    gate_tier: str | None = None,
) -> dict[str, Any]:
    """Build one stable, machine-readable execution timing record."""
    normalized_files = _normalize_changed_files(changed_files)
    impact = minimum_acceptance_route(normalized_files)
    actual_tier = normalize_gate_tier(gate_tier or impact["minimum_gate_tier"])
    normalized_head = _normalize_optional_text(head_sha, "head_sha")
    duration = _non_negative_finite(duration_s, "duration_s")
    lease_wait = _non_negative_finite(simulator_lease_wait_s, "simulator_lease_wait_s")
    return {
        "schema": TIMING_CONTRACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "head_sha": normalized_head,
        "changed_files": normalized_files,
        "ticket": _normalize_optional_text(ticket, "ticket"),
        "packet": _normalize_optional_text(packet, "packet"),
        "gate_tier": actual_tier,
        "minimum_gate_tier": impact["minimum_gate_tier"],
        "acceptance_route": impact["acceptance_route"],
        "command": _normalize_command(command),
        "duration_s": round(duration, 3),
        "simulator_lease_wait_s": round(lease_wait, 3),
        "cache_status": normalize_cache_status(cache_status),
        "tier_compliant": _TIER_RANK[actual_tier] >= _TIER_RANK[impact["minimum_gate_tier"]],
    }


__all__ = [
    "CACHE_STATUSES",
    "CONTRACT_VERSION",
    "GATE_TIERS",
    "IMPACT_SCHEMA",
    "MeasurementContractError",
    "TIMING_CONTRACT_SCHEMA",
    "build_timing_contract",
    "minimum_acceptance_route",
    "normalize_cache_status",
    "normalize_gate_tier",
]
