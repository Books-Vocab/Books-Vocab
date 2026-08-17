"""Explicit test routes for the worktree orchestrator.

The route table is deliberately data-first.  A changed source path either names a
small selector bundle, names its owning behavior group, or falls back to the complete
orchestrator group.  It must never turn an unknown path into an empty green run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from fnmatch import fnmatch
from typing import Any


ROUTE_SCHEMA = "kg.test.route.v1"
ROUTE_VERSION = 1
PYTEST_PREFIX = (
    "uv", "run", "--no-project", "--python", "3.13",
    "--with", "pytest", "--with", "pyjwt", "--with", "cryptography",
    "pytest",
)

_ORCHESTRATOR_SURFACE_PATTERNS = (
    "ops/worktree_orchestrate*.py",
    "ops/lib/worktree_orchestrator_*.py",
    "ops/test_route.py",
    "ops/lib/worktree_test_routes.py",
)


def _route(
    route_id: str,
    source_patterns: list[str],
    selector: str,
    nodeids: list[str],
    resource_class: str = "ops-python",
    gate_tier: str = "S1",
) -> dict[str, Any]:
    return {
        "route_id": route_id,
        "source_patterns": source_patterns,
        "pytest_nodeids": nodeids,
        "selectors": [selector],
        "fallback_test_file": selector,
        "gate_tier": gate_tier,
        "failure_policy": "block",
        "resource_class": resource_class,
    }


_BEHAVIOR_ROUTES: tuple[dict[str, Any], ...] = (
    _route(
        "orchestrator.planning",
        ["ops/lib/worktree_orchestrator_planning.py",
         "ops/tests/test_worktree_orchestrate_planning.py"],
        "ops/tests/test_worktree_orchestrate_planning.py",
        [
            "ops/tests/test_worktree_orchestrate_planning.py::"
            "test_usage_errors_return_contract_code_for_root_and_subparser_typos",
            "ops/tests/test_worktree_orchestrate_planning.py::"
            "test_gate_omission_always_plans_official_deck_check",
        ],
    ),
    _route(
        "orchestrator.gate",
        ["ops/lib/worktree_orchestrator_gate.py",
         "ops/lib/worktree_orchestrator_core_gate_execution.py",
         "ops/tests/test_worktree_orchestrate_gate.py"],
        "ops/tests/test_worktree_orchestrate_gate.py",
        [
            "ops/tests/test_worktree_orchestrate_gate.py::"
            "test_streamed_gate_runner_heartbeats_to_stderr_and_keeps_stdout_pure",
            "ops/tests/test_worktree_orchestrate_gate.py::"
            "test_shell_and_internal_gate_results_carry_duration",
        ],
    ),
    _route(
        "orchestrator.lifecycle",
        ["ops/lib/worktree_orchestrator_lifecycle.py",
         "ops/lib/worktree_orchestrator_landing.py",
         "ops/lib/worktree_orchestrator_resolve.py",
         "ops/tests/test_worktree_orchestrate_lifecycle.py"],
        "ops/tests/test_worktree_orchestrate_lifecycle.py",
        [
            "ops/tests/test_worktree_orchestrate_lifecycle.py::"
            "test_open_cutover_resolve_roundtrip_leaves_no_residue",
            "ops/tests/test_worktree_orchestrate_lifecycle.py::"
            "test_cutover_refuses_required_tier_metadata_drift",
        ],
    ),
    _route(
        "orchestrator.claims",
        ["ops/lib/worktree_orchestrator_claims.py",
         "ops/tests/test_worktree_orchestrate_claims.py"],
        "ops/tests/test_worktree_orchestrate_claims.py",
        [
            "ops/tests/test_worktree_orchestrate_claims.py::"
            "test_open_refuses_a_ticket_another_worktree_already_holds",
            "ops/tests/test_worktree_orchestrate_claims.py::"
            "test_open_without_a_ticket_still_works_and_claims_nothing",
        ],
    ),
    _route(
        "orchestrator.delivery",
        ["ops/lib/worktree_orchestrator_delivery.py",
         "ops/lib/worktree_orchestrator_integration.py",
         "ops/lib/worktree_orchestrator_close_wave.py",
         "ops/lib/worktree_orchestrator_delivery_anchor.py",
         "ops/lib/worktree_orchestrator_delivery_support.py",
         "ops/tests/test_worktree_orchestrate_delivery.py"],
        "ops/tests/test_worktree_orchestrate_delivery.py",
        [
            "ops/tests/test_worktree_orchestrate_delivery.py::"
            "test_gate_tiering_and_deferral_flags_are_preserved_by_each_delivery_entrypoint",
            "ops/tests/test_worktree_orchestrate_delivery.py::"
            "test_cutover_stamps_the_landed_sha_onto_this_branchs_staged_closures",
        ],
    ),
    _route(
        "orchestrator.recovery",
        ["ops/lib/worktree_orchestrator_repair.py",
         "ops/tests/test_worktree_orchestrate_recovery.py"],
        "ops/tests/test_worktree_orchestrate_recovery.py",
        [
            "ops/tests/test_worktree_orchestrate_recovery.py::"
            "test_delivery_anchor_guard_checks_primary_branch_inside_advance_lock",
            "ops/tests/test_worktree_orchestrate_recovery.py::"
            "test_delivery_anchor_noop_marker_empty_queue_is_explicit_noop_and_replayable",
        ],
    ),
)

_FACADE_ROUTE = _route(
    "orchestrator.facade",
    [
        "ops/worktree_orchestrate.py",
        "ops/lib/worktree_orchestrator_runtime.py",
        "ops/lib/worktree_gate_tiers.py",
        "ops/tests/worktree_orchestrate_support.py",
        "ops/tests/test_orchestrator_seams.py",
    ],
    "ops/tests/test_orchestrator_seams.py",
    [
        "ops/tests/test_orchestrator_seams.py::"
        "test_legacy_commands_remain_reexported_from_the_facade",
        "ops/tests/test_orchestrator_seams.py::"
        "test_legacy_collector_matches_split_behavior_collection",
    ],
)
# Gate-tier policy is part of the facade/runtime seam, but its direct policy
# tests must travel with a focused route as well; otherwise changing the tier
# classifier can pass facade smoke while its own contract suite is untouched.
_FACADE_ROUTE["selectors"].append("ops/tests/test_worktree_gate_tiers.py")
_FACADE_ROUTE["pytest_nodeids"].extend([
    "ops/tests/test_worktree_gate_tiers.py::"
    "test_s4_is_an_explicit_release_profile_and_has_no_deferrable_gate",
    "ops/tests/test_worktree_gate_tiers.py::"
    "test_only_named_non_high_s2_s3_failures_can_be_deferred",
])

_ALL_ROUTES: tuple[dict[str, Any], ...] = (*_BEHAVIOR_ROUTES, _FACADE_ROUTE)
_ROUTES_BY_ID = {route["route_id"]: route for route in _ALL_ROUTES}
_FACADE_PATTERNS = set(_FACADE_ROUTE["source_patterns"][:-1])
_LEGACY_PATH = "ops/tests/test_worktree_orchestrate.py"

_FALLBACK_ROUTE: dict[str, Any] = {
    "route_id": "orchestrator.fallback",
    "source_patterns": ["*"],
    "pytest_nodeids": [],
    "selectors": [route["selectors"][0] for route in (*_BEHAVIOR_ROUTES, _FACADE_ROUTE)],
    "fallback_test_file": "ops/tests",
    "gate_tier": "S2",
    "failure_policy": "block",
    "resource_class": "ops-python",
}


def route_manifest() -> dict[str, Any]:
    """Return a defensive copy of the machine-readable route manifest."""
    return {
        "schema": ROUTE_SCHEMA,
        "version": ROUTE_VERSION,
        "routes": deepcopy(list(_ALL_ROUTES)),
        "fallback": deepcopy(_FALLBACK_ROUTE),
    }


def route_ids() -> tuple[str, ...]:
    return tuple(_ROUTES_BY_ID)


def _matches(path: str, pattern: str) -> bool:
    return path == pattern or fnmatch(path, pattern)


def is_orchestrator_source(path: str) -> bool:
    """Whether a changed path belongs to this route manifest's source surface."""
    return path == _LEGACY_PATH or any(
        _matches(path, pattern) for pattern in _ORCHESTRATOR_SURFACE_PATTERNS
    ) or any(
        any(_matches(path, pattern) for pattern in route["source_patterns"])
        for route in _ALL_ROUTES
    )


def _known_routes(changed_files: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    routes: list[dict[str, Any]] = []
    reasons: list[str] = []
    source_list = list(changed_files)
    if any(path in _FACADE_PATTERNS for path in source_list):
        routes.extend(_BEHAVIOR_ROUTES)
        routes.append(_FACADE_ROUTE)
        reasons.append("facade/runtime change unions all behavior routes")
    for path in source_list:
        if path in _FACADE_PATTERNS:
            continue
        matched = [
            route for route in _BEHAVIOR_ROUTES
            if any(_matches(path, pattern) for pattern in route["source_patterns"])
        ]
        if path == _LEGACY_PATH:
            matched = list(_BEHAVIOR_ROUTES)
            reasons.append("legacy collector change unions all behavior routes")
        if not matched:
            return [], [f"unknown orchestrator source: {path}"]
        routes.extend(matched)
    unique = {route["route_id"]: route for route in routes}
    return [unique[key] for key in sorted(unique)], reasons


def _route_files_exist(
    routes: Iterable[dict[str, Any]],
    exists: Callable[[str], bool] | None,
) -> list[str]:
    if exists is None:
        return []
    missing: list[str] = []
    for route in routes:
        for path in (*route["selectors"], route["fallback_test_file"]):
            if path not in missing and not exists(path):
                missing.append(path)
    return missing


def resolve_routes(
    changed_files: Iterable[str],
    *,
    route_version: int = ROUTE_VERSION,
    exists: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Resolve changed files without permitting an empty test command.

    ``exists`` is injected by the gate and points at the target worktree.  Pure callers
    may omit it; they still get deterministic route selection, while the executable
    gate can fail-safe when a selector was deleted in the same diff.
    """
    changed = sorted({str(path) for path in changed_files})
    if route_version != ROUTE_VERSION:
        return _fallback_payload(changed, [f"route version {route_version} is unsupported"])
    if not changed:
        return _fallback_payload(changed, ["no source paths were supplied"])
    routes, reasons = _known_routes(changed)
    if not routes:
        return _fallback_payload(changed, reasons)
    missing = _route_files_exist(routes, exists)
    if missing:
        return _fallback_payload(changed, ["route selectors missing: " + ", ".join(missing)])
    return {
        "schema": ROUTE_SCHEMA,
        "version": ROUTE_VERSION,
        "changed_files": changed,
        "fallback": False,
        "reasons": reasons,
        "routes": deepcopy(routes),
    }


def _fallback_payload(changed: list[str], reasons: list[str]) -> dict[str, Any]:
    return {
        "schema": ROUTE_SCHEMA,
        "version": ROUTE_VERSION,
        "changed_files": changed,
        "fallback": True,
        "reasons": reasons,
        "routes": [deepcopy(_FALLBACK_ROUTE)],
    }


def routes_for_ids(route_id_values: Iterable[str]) -> list[dict[str, Any]]:
    """Resolve route ids; unknown ids fail-safe to the complete group."""
    ids = list(dict.fromkeys(str(value) for value in route_id_values))
    if not ids or any(value not in _ROUTES_BY_ID for value in ids):
        return [deepcopy(_FALLBACK_ROUTE)]
    return [deepcopy(_ROUTES_BY_ID[value]) for value in ids]


def pytest_command(
    routes: Iterable[dict[str, Any]],
    *,
    focused: bool,
    collect_only: bool = False,
) -> list[str]:
    """Build the pinned pytest command for a focused or group execution."""
    selected = list(routes)
    if not selected:
        selected = [deepcopy(_FALLBACK_ROUTE)]
    values: list[str] = []
    key = "pytest_nodeids" if focused else "selectors"
    for route in selected:
        values.extend(str(value) for value in route.get(key, []))
    if not values:
        values = list(_FALLBACK_ROUTE["selectors"])
    values = list(dict.fromkeys(values))
    command = [*PYTEST_PREFIX, "-q"]
    if collect_only:
        command.append("--collect-only")
    return [*command, *values]


def runner_route_args(route_payload: dict[str, Any], *, focused: bool) -> list[str]:
    """Return stable args for ``ops/test_route.py`` without embedding raw argv."""
    routes = route_payload.get("routes") or [_FALLBACK_ROUTE]
    ids = [route["route_id"] for route in routes]
    return ["ops/test_route.py", "run", "--mode", "focused" if focused else "group",
            "--route-id", *ids]
