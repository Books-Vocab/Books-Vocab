"""Pure contracts for gate timing evidence and changed-file impact routing.

This module intentionally has no filesystem, git, subprocess, or environment
access.  It turns caller-supplied execution facts into stable JSON-shaped
records and chooses the cheapest honest acceptance route for a changed-file
set.  Runners own measurement; this module owns only normalization and policy.
"""

from __future__ import annotations

import math
import posixpath
import re
from collections.abc import Iterable
from typing import Any

from lib import worktree_gate_tiers as existing_tiers

TIMING_CONTRACT_SCHEMA = "kg.test.timing.contract.v1"
IMPACT_SCHEMA = "kg.test.impact.v1"
ACCEPTANCE_ROUTE_SCHEMA = "kg.test.impact.route.v1"
CONTRACT_VERSION = 1
GATE_TIERS = existing_tiers.GATE_TIERS
_TIER_RANK = existing_tiers.TIER_RANK
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
_NEUTRAL_PREFIXES = ("docs/", "README", "CHANGELOG", "LICENSE")
_SAFE_COMMAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_UI_PATH_MARKERS = (
    "/views/", "/ui/", "/uicomponents/", "/components/", "/uitests/", "/snapshots/",
)
ACCEPTANCE_ROUTES: dict[str, dict[str, Any]] = {
    "static": {"route_id": "impact.static", "tier": "S0"},
    "unit-ops": {"route_id": "impact.unit-ops", "tier": "S1"},
    "ui-precise": {"route_id": "impact.ui-precise", "tier": "S2"},
    "full-gate": {"route_id": "impact.full-gate", "tier": "S3"},
}


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
        if path in {"", "."} or path.startswith(("/", "../")) or path == "..":
            raise MeasurementContractError(f"changed file path must be repository-relative: {raw_path!r}")
        normalized.add(path.removeprefix("./"))
    return sorted(normalized)


def _normalize_command(command: str) -> str:
    """Keep a semantic command key; never persist raw argv or shell text."""
    if not isinstance(command, str) or not _SAFE_COMMAND.fullmatch(command.strip()):
        raise MeasurementContractError(
            "command must be a safe semantic command key; raw argv is not recorded"
        )
    return command.strip()


def _normalize_optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MeasurementContractError(f"{field} must be a non-empty string or null")
    return value.strip()


def normalize_gate_tier(value: str) -> str:
    try:
        return existing_tiers.normalize_gate_tier(value)
    except existing_tiers.GateTierError as exc:
        raise MeasurementContractError(str(exc)) from exc


def normalize_cache_status(value: str | None) -> str:
    candidate = "unknown" if value is None else str(value).strip().lower()
    candidate = _CACHE_ALIASES.get(candidate, candidate)
    if candidate not in CACHE_STATUSES:
        allowed = ", ".join(sorted(CACHE_STATUSES))
        raise MeasurementContractError(
            f"cache_status must be one of {allowed}; got {value!r}"
        )
    return candidate


def _non_negative_finite(value: float, field: str) -> float:
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
        or ("snapshot" in basename and parts[0] in _FUNCTIONAL_ROOTS)
    )


def _is_control_plane(path: str) -> bool:
    if path in _CONTROL_PLANE_EXACT:
        return True
    return path.startswith((
        "ops/lib/worktree_orchestrator_", "ops/worktree_registry.py",
        "ops/context_route.py", "ops/skill_route.py",
        ".github/", ".claude/skills/",
    ))


def _is_ui_surface(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith("ios/") and (
        any(marker in lowered for marker in _UI_PATH_MARKERS)
        or lowered.endswith((".storyboard", ".xib"))
    )


def _is_neutral(path: str) -> bool:
    return path.startswith(_NEUTRAL_PREFIXES) or path in {".gitignore", "LICENSE"}


def minimum_acceptance_route(
    changed_files: Iterable[str] | None,
    planned_plan: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    unknown_surface = sorted(
        path for path in paths
        if not _is_neutral(path)
        and path.split("/", 1)[0] not in _FUNCTIONAL_ROOTS
        and not _is_control_plane(path)
    )

    reasons: list[str] = []
    if len(functional_roots) >= 2:
        reasons.append("cross-functional-surface")
    if control_plane:
        reasons.append("control-plane")
    if shared_fixtures:
        reasons.append("shared-fixture")
    if unknown_surface:
        reasons.append("unknown-surface")

    if reasons:
        minimum_tier, acceptance_route = "S3", "full-gate"
    elif ui_files or "design-system" in functional_roots:
        minimum_tier, acceptance_route = "S2", "ui-precise"
    elif functional_roots:
        minimum_tier, acceptance_route = "S1", "unit-ops"
    else:
        minimum_tier, acceptance_route = "S0", "static"

    route = ACCEPTANCE_ROUTES[acceptance_route]
    return {
        "schema": IMPACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "changed_files": paths,
        "route_schema": ACCEPTANCE_ROUTE_SCHEMA,
        "route_id": route["route_id"],
        "acceptance_route": acceptance_route,
        "minimum_acceptance_tier": minimum_tier,
        "required_cutover_tier": existing_tiers.required_cutover_tier(paths, planned_plan),
        "escalation_reasons": sorted(reasons),
    }


def build_timing_contract(
    *,
    head_sha: str | None,
    changed_files: Iterable[str] | None,
    command: str,
    duration_s: float,
    simulator_lease_wait_s: float = 0.0,
    cache_status: str | None = None,
    ticket: str | None = None,
    packet: str | None = None,
    gate_tier: str | None = None,
) -> dict[str, Any]:
    """Build one stable, machine-readable execution timing record."""
    normalized_files = _normalize_changed_files(changed_files)
    impact = minimum_acceptance_route(normalized_files)
    actual_tier = normalize_gate_tier(gate_tier) if gate_tier and str(gate_tier).strip() else None
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
        "minimum_acceptance_tier": impact["minimum_acceptance_tier"],
        "required_cutover_tier": impact["required_cutover_tier"],
        "route_schema": impact["route_schema"],
        "route_id": impact["route_id"],
        "acceptance_route": impact["acceptance_route"],
        "command": _normalize_command(command),
        "duration_s": round(duration, 3),
        "simulator_lease_wait_s": round(lease_wait, 3),
        "cache_status": normalize_cache_status(cache_status),
        "tier_compliant": (
            actual_tier is not None
            and _TIER_RANK[actual_tier] >= _TIER_RANK[impact["minimum_acceptance_tier"]]
        ),
    }


__all__ = [
    "ACCEPTANCE_ROUTES",
    "ACCEPTANCE_ROUTE_SCHEMA",
    "CACHE_STATUSES",
    "CONTRACT_VERSION",
    "GATE_TIERS",
    "IMPACT_SCHEMA",
    "TIMING_CONTRACT_SCHEMA",
    "MeasurementContractError",
    "build_timing_contract",
    "minimum_acceptance_route",
    "normalize_cache_status",
    "normalize_gate_tier",
]
