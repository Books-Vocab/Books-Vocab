#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Pure, machine-readable planning for the expensive parts of a gate run.

This module deliberately does not execute ``ops/test_ops.sh``, boot a simulator,
touch DerivedData, or acquire an OS lock.  It describes the smallest affected
runner groups and the resources that a later Manager-owned entrypoint may use.
That keeps planning cheap and makes a resource decision testable without an
iOS toolchain.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOPOLOGY_SCHEMA = "kg.gate.test-topology.v1"
IMPACT_SCHEMA = "kg.gate.group-impact.v1"
LEASE_SCHEMA = "kg.ios.simulator-lease.v1"
READINESS_SCHEMA = "kg.ios.derived-data-readiness.v1"
RUN_COST_SCHEMA = "kg.gate.run-cost.v1"
RESOURCE_PLAN_SCHEMA = "kg.gate.resource-plan.v1"
PLAN_VERSION = 1


class PlanContractError(ValueError):
    """Raised when a caller supplies an unsafe or ambiguous plan input."""


_GROUP_NAME_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\)(.*)$")
_REPO_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:\./)?(ops/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:sh|py))\b"
)
_GROUPS_RE = re.compile(
    r"(?ms)^\s*(DEFAULT_TESTS|OPTIONAL_TESTS)=\(\n(?P<body>.*?)^\)\s*$"
)
_VALID_READINESS = frozenset(
    {
        "ready",
        "missing",
        "incomplete",
        "stale-head",
        "stale-definition",
        "clean-rebuild-required",
    }
)
_CLEAN_REBUILD_STATUSES = frozenset(
    {
        "incomplete",
        "stale-head",
        "stale-definition",
        "clean-rebuild-required",
    }
)


@dataclass(frozen=True)
class _RunnerGroup:
    name: str
    optional: bool
    command_paths: tuple[str, ...]


@dataclass(frozen=True)
class _GroupProfile:
    responsibility: str
    resources: tuple[str, ...] = ("ops-python",)
    impact_patterns: tuple[str, ...] = ()


# The profiles are intentionally small.  The runner remains the source for the
# group inventory and command arms; this table only records the responsibility
# and shared-resource contract that a future runner can consume.
_GROUP_PROFILES: dict[str, _GroupProfile] = {
    "worktree-orchestrator": _GroupProfile(
        "worktree/gate planning, lifecycle, registry, and timing contracts",
        impact_patterns=(
            "ops/worktree_orchestrate.py",
            "ops/lib/worktree_*.py",
            "ops/lib/test_timing_store.py",
            "ops/test_timing.py",
            "ops/gate_cost_execution_plan.py",
            "ops/tests/test_gate_cost_execution_plan.py",
            "ops/tests/test_worktree_*.py",
            "ops/tests/test_orchestrator_seams.py",
            "ops/tests/test_test_timing*.py",
        ),
    ),
    "ops-ci-coverage": _GroupProfile(
        "aggregate runner reachability and group-chain coverage",
        impact_patterns=(
            "ops/test_ops.sh",
            "ops/tests/test_ops_ci_coverage.sh",
            "ops/tests/test_ops_group_chain.py",
            "ops/tests/test_ci_expected_fail_exclusions.py",
        ),
    ),
    "ios-ops": _GroupProfile(
        "iOS operations facade, diagnostics, coverage, and build-target contracts",
        resources=("derived-data", "simulator"),
        impact_patterns=(
            "ops/ios_ops.sh",
            "ops/ios_build.sh",
            "ops/ios_archive.sh",
            "ops/test_ios_ops.sh",
            "ops/ios_diagnostics.py",
            "ops/ios_coverage.py",
            "ops/lib/ios_ops_*.sh",
            "ops/lib/ios_build_progress.sh",
            "ops/lib/ios_run_metrics.sh",
            "ops/tests/test_ios_ops_release_heartbeat.sh",
            "ops/tests/test_ios_ui_test_package_dependencies.sh",
            "ops/tests/test_ios_build_covers_test_targets.sh",
            "ops/tests/test_ios_diagnostics.py",
            "ops/tests/test_ios_coverage.py",
        ),
    ),
    "ios-test-discovery": _GroupProfile(
        "iOS test discovery and selector contract",
        resources=("derived-data",),
        impact_patterns=(
            "ops/ios_test.sh",
            "ops/test_ios_test_discovery.sh",
            "ops/lib/ios_test_discovery.sh",
        ),
    ),
    "ios-cache-evict": _GroupProfile(
        "iOS test-cache and DerivedData lifecycle contracts",
        resources=("derived-data",),
        impact_patterns=(
            "ops/lib/ios_cache_evict.sh",
            "ops/lib/ios_test_cache_root.sh",
            "ops/tests/test_ios_cache_evict.sh",
            "ops/tests/test_ios_test_cache_root.sh",
            "ops/tests/test_ios_build_cache_lifecycle.sh",
            "ops/tests/test_ios_xctestrun_cache.sh",
        ),
    ),
    "ios-device-lock": _GroupProfile(
        "iOS simulator/device execution-lock ownership and fairness",
        resources=("simulator",),
        impact_patterns=(
            "ops/lib/ios_lock_wait.sh",
            "ops/tests/test_ios_device_lock_verdict.sh",
        ),
    ),
    "sim-pool-disposable": _GroupProfile(
        "disposable simulator-pool lease and stale-slot cleanup",
        resources=("simulator-pool",),
        impact_patterns=(
            "ops/lib/ios_ops_simulator.sh",
            "ops/tests/test_ios_ops_sim_pool_disposable.sh",
        ),
    ),
    "ios-device-files": _GroupProfile(
        "simulator/device file transfer contract",
        resources=("simulator",),
        impact_patterns=(
            "ops/ios_device_files.sh",
            "ops/tests/test_ios_device_files.sh",
        ),
    ),
    "ios-device-logs": _GroupProfile(
        "simulator/device log collection contract",
        resources=("simulator",),
        impact_patterns=("ops/ios_device_logs.sh", "ops/tests/test_ios_device_logs.sh"),
    ),
    "ios-run-verdict": _GroupProfile(
        "iOS test-run verdict and failure classification",
        resources=("simulator",),
        impact_patterns=(
            "ops/lib/ios_run_verdict.sh",
            "ops/tests/test_ios_run_verdict.sh",
        ),
    ),
    "ios-install-provenance": _GroupProfile(
        "iOS app installation provenance and identity",
        resources=("simulator",),
        impact_patterns=(
            "ops/lib/ios_install_provenance.sh",
            "ops/tests/test_ios_install_provenance.sh",
        ),
    ),
    "ios-signal-traps": _GroupProfile(
        "iOS signal/trap cleanup contract",
        resources=("simulator",),
        impact_patterns=("ops/tests/test_ios_signal_traps.sh",),
    ),
    "gen-ios-baseline": _GroupProfile(
        "generated iOS source-size baseline contract",
        impact_patterns=(
            "ops/gen_ios_baseline.sh",
            "ops/tests/test_gen_ios_baseline.sh",
        ),
    ),
    "ios-release": _GroupProfile(
        "iOS archive/release surface contract",
        resources=("derived-data", "simulator"),
        impact_patterns=("ops/ios_release.sh", "ops/test_ios_release.sh"),
    ),
}


def _normalise_path(value: str) -> str:
    if not isinstance(value, str):
        raise PlanContractError("changed file paths must be strings")
    path = value.strip()
    if not path or any(char.isspace() for char in path):
        raise PlanContractError(f"invalid changed file path: {value!r}")
    if path.startswith(("/", "../")) or path == "." or "/../" in f"/{path}/":
        raise PlanContractError(
            f"changed file path must be repository-relative: {value!r}"
        )
    return path.removeprefix("./")


def _parse_group_arrays(source: str) -> tuple[list[str], list[str]]:
    arrays: dict[str, list[str]] = {"DEFAULT_TESTS": [], "OPTIONAL_TESTS": []}
    for match in _GROUPS_RE.finditer(source):
        values = [
            value
            for value in re.findall(
                r"(?m)^\s*([A-Za-z][A-Za-z0-9_-]*)\s*$", match.group("body")
            )
            if value not in arrays[match.group(1)]
        ]
        arrays[match.group(1)] = values
    return arrays["DEFAULT_TESTS"], arrays["OPTIONAL_TESTS"]


def _parse_case_arms(source: str) -> dict[str, str]:
    start = source.find('case "$1" in')
    if start < 0:
        raise PlanContractError("ops/test_ops.sh has no run_one case")
    arms: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in source[start:].splitlines()[1:]:
        if line.strip() == "esac":
            break
        match = _GROUP_NAME_RE.match(line)
        if match:
            current = match.group(1)
            body = []
            inline = match.group(2)
            if ";;" in inline:
                body.append(inline.split(";;", 1)[0])
                arms[current] = "\n".join(body)
                current = None
            else:
                body.append(inline)
            continue
        if current is None:
            continue
        if ";;" in line:
            body.append(line.split(";;", 1)[0])
            arms[current] = "\n".join(body)
            current = None
        else:
            body.append(line)
    if current is not None:
        raise PlanContractError(f"runner group {current!r} has no terminator")
    if not arms:
        raise PlanContractError("ops/test_ops.sh has no group arms")
    return arms


def _runner_groups(source: str) -> tuple[_RunnerGroup, ...]:
    default, optional = _parse_group_arrays(source)
    arms = _parse_case_arms(source)
    order = [*default, *optional]
    # Keep a group visible if the runner has an arm but forgot to list it in an
    # inventory array; the caller can then report the topology drift.
    order.extend(name for name in arms if name not in order and name != "*")
    groups: list[_RunnerGroup] = []
    for name in order:
        arm = arms.get(name, "")
        paths = tuple(sorted(set(_REPO_PATH_RE.findall(arm))))
        groups.append(_RunnerGroup(name, name in optional, paths))
    return tuple(groups)


def _profile_for(name: str) -> _GroupProfile:
    return _GROUP_PROFILES.get(
        name,
        _GroupProfile(f"ops/test_ops.sh {name} contract group"),
    )


def build_topology(
    root: str | Path | None = None, *, source: str | None = None
) -> dict[str, Any]:
    """Return the current runner inventory plus resource/impact metadata.

    ``source`` is injectable for contract tests.  Production callers normally
    pass a repository root and let this function read only ``ops/test_ops.sh``.
    """

    repo_root = Path(root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    runner_path = repo_root / "ops/test_ops.sh"
    runner_source = (
        source if source is not None else runner_path.read_text(encoding="utf-8")
    )
    default, optional = _parse_group_arrays(runner_source)
    groups = _runner_groups(runner_source)
    payload_groups: list[dict[str, Any]] = []
    for group in groups:
        profile = _profile_for(group.name)
        payload_groups.append(
            {
                "name": group.name,
                "optional": group.optional,
                "command": ["./ops/test_ops.sh", group.name],
                "command_paths": list(group.command_paths),
                "responsibility": profile.responsibility,
                "resources": list(profile.resources),
                "impact_patterns": list(profile.impact_patterns),
            }
        )
    return {
        "schema": TOPOLOGY_SCHEMA,
        "version": PLAN_VERSION,
        "runner": "ops/test_ops.sh",
        "default_groups": default,
        "optional_groups": optional,
        "groups": payload_groups,
    }


def _group_matches_path(group: Mapping[str, Any], path: str) -> bool:
    return any(
        fnmatch.fnmatchcase(path, str(pattern))
        for pattern in group.get("impact_patterns", [])
    )


def select_minimal_groups(
    changed_files: Iterable[str],
    *,
    root: str | Path | None = None,
    topology: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select only the runner groups whose declared surface is impacted.

    Unknown paths remain explicit in ``unmatched``.  They never trigger the
    aggregate runner as a safety-by-volume fallback.
    """

    changed = sorted({_normalise_path(path) for path in changed_files})
    topo = dict(topology or build_topology(root))
    groups = list(topo.get("groups", []))
    by_name = {str(group["name"]): group for group in groups}
    selected: set[str] = set()
    unmatched: list[str] = []
    reasons: list[str] = []

    for path in changed:
        if path == "ops/test_ops.sh" and "ops-ci-coverage" in by_name:
            selected.add("ops-ci-coverage")
            reasons.append(
                "aggregate runner changed; select reachability coverage only"
            )
            continue
        exact = [
            str(group["name"])
            for group in groups
            if path in {str(value) for value in group.get("command_paths", [])}
        ]
        # A path already wired to an existing arm must not grow a second group
        # merely because a profile also documents its resource.  Profiles are
        # the fallback for source paths and for new tests awaiting central
        # runner wiring.
        matches = exact or [
            str(group["name"]) for group in groups if _group_matches_path(group, path)
        ]
        if matches:
            selected.update(matches)
            reasons.append(f"{path} -> {', '.join(matches)}")
        else:
            unmatched.append(path)

    ordered = [str(group["name"]) for group in groups if str(group["name"]) in selected]
    return {
        "schema": IMPACT_SCHEMA,
        "version": PLAN_VERSION,
        "changed_files": changed,
        "groups": ordered,
        "unmatched": sorted(unmatched),
        "fallback": False,
        "reasons": reasons or (["no changed files"] if not changed else []),
    }


@dataclass(frozen=True)
class SimulatorLease:
    """Serializable reservation identity; it does not acquire a real device."""

    pool: str
    udid: str
    runtime: str
    device_type: str
    owner: str
    booted: bool = False

    def __post_init__(self) -> None:
        for field in ("pool", "udid", "runtime", "device_type", "owner"):
            if (
                not isinstance(getattr(self, field), str)
                or not getattr(self, field).strip()
            ):
                raise PlanContractError(f"simulator lease {field} must be non-empty")

    @property
    def resource_key(self) -> str:
        return f"simulator:{self.udid}:{self.runtime}"

    def can_release(self, owner: str) -> bool:
        return isinstance(owner, str) and owner == self.owner

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SimulatorLease:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise PlanContractError("simulator must be a SimulatorLease mapping")
        return cls(
            pool=str(value.get("pool", "")),
            udid=str(value.get("udid", "")),
            runtime=str(value.get("runtime", "")),
            device_type=str(value.get("device_type", "")),
            owner=str(value.get("owner", "")),
            booted=bool(value.get("booted", False)),
        )

    def for_owner(self, owner: str) -> SimulatorLease:
        if not isinstance(owner, str) or not owner.strip():
            raise PlanContractError("simulator lease owner must be non-empty")
        return SimulatorLease(
            pool=self.pool,
            udid=self.udid,
            runtime=self.runtime,
            device_type=self.device_type,
            owner=owner,
            booted=self.booted,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LEASE_SCHEMA,
            "version": PLAN_VERSION,
            "resource_key": self.resource_key,
            "pool": self.pool,
            "udid": self.udid,
            "runtime": self.runtime,
            "device_type": self.device_type,
            "owner": self.owner,
            "booted": self.booted,
        }


@dataclass(frozen=True)
class DerivedDataReadiness:
    """A read-only verdict on whether a build/test cache is safe to reuse."""

    cache_key: str
    status: str
    path: str | None = None
    reason: str = ""
    actual_head: str | None = None
    expected_head: str | None = None
    actual_definition_digest: str | None = None
    expected_definition_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.cache_key, str) or not self.cache_key.strip():
            raise PlanContractError("DerivedData cache_key must be non-empty")
        if self.status not in _VALID_READINESS:
            raise PlanContractError(f"unknown DerivedData readiness: {self.status!r}")

    @classmethod
    def assess(
        cls,
        *,
        cache_key: str,
        path: str | None,
        exists: bool,
        ready_marker: bool,
        actual_head: str | None,
        expected_head: str | None,
        actual_definition_digest: str | None,
        expected_definition_digest: str | None,
    ) -> DerivedDataReadiness:
        if not exists:
            return cls(
                cache_key,
                "missing",
                path=path,
                reason="cache path is absent",
                expected_head=expected_head,
                expected_definition_digest=expected_definition_digest,
            )
        if not ready_marker:
            return cls(
                cache_key,
                "incomplete",
                path=path,
                reason="ready marker is absent",
                actual_head=actual_head,
                expected_head=expected_head,
                actual_definition_digest=actual_definition_digest,
                expected_definition_digest=expected_definition_digest,
            )
        if expected_head is not None and actual_head != expected_head:
            return cls(
                cache_key,
                "stale-head",
                path=path,
                reason="source HEAD changed",
                actual_head=actual_head,
                expected_head=expected_head,
                actual_definition_digest=actual_definition_digest,
                expected_definition_digest=expected_definition_digest,
            )
        if (
            expected_definition_digest is not None
            and actual_definition_digest != expected_definition_digest
        ):
            return cls(
                cache_key,
                "stale-definition",
                path=path,
                reason="test/build definition changed",
                actual_head=actual_head,
                expected_head=expected_head,
                actual_definition_digest=actual_definition_digest,
                expected_definition_digest=expected_definition_digest,
            )
        return cls(
            cache_key,
            "ready",
            path=path,
            reason="cache identity is current",
            actual_head=actual_head,
            expected_head=expected_head,
            actual_definition_digest=actual_definition_digest,
            expected_definition_digest=expected_definition_digest,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> DerivedDataReadiness:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise PlanContractError(
                "derived_data must be a DerivedDataReadiness mapping"
            )
        return cls(
            cache_key=str(value.get("cache_key", "")),
            status=str(value.get("status", "")),
            path=value.get("path"),
            reason=str(value.get("reason", "")),
            actual_head=value.get("actual_head"),
            expected_head=value.get("expected_head"),
            actual_definition_digest=value.get("actual_definition_digest"),
            expected_definition_digest=value.get("expected_definition_digest"),
        )

    @classmethod
    def ready(cls, cache_key: str, *, path: str | None = None) -> DerivedDataReadiness:
        return cls(cache_key, "ready", path=path, reason="cache identity is current")

    @classmethod
    def missing(
        cls, cache_key: str, *, path: str | None = None
    ) -> DerivedDataReadiness:
        return cls(cache_key, "missing", path=path, reason="cache path is absent")

    @classmethod
    def clean_rebuild(cls, cache_key: str, *, reason: str) -> DerivedDataReadiness:
        return cls(cache_key, "clean-rebuild-required", reason=reason)

    @property
    def can_reuse(self) -> bool:
        return self.status == "ready"

    @property
    def requires_clean_rebuild(self) -> bool:
        return self.status in _CLEAN_REBUILD_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": READINESS_SCHEMA,
            "version": PLAN_VERSION,
            "cache_key": self.cache_key,
            "path": self.path,
            "status": self.status,
            "reason": self.reason,
            "can_reuse": self.can_reuse,
            "requires_clean_rebuild": self.requires_clean_rebuild,
            "actual_head": self.actual_head,
            "expected_head": self.expected_head,
            "actual_definition_digest": self.actual_definition_digest,
            "expected_definition_digest": self.expected_definition_digest,
        }


def decide_run_cost(
    *,
    simulator: SimulatorLease | None,
    derived_data: DerivedDataReadiness,
    needs_simulator: bool,
) -> dict[str, Any]:
    """Classify the cheapest honest run without hiding a required rebuild."""

    if not isinstance(derived_data, DerivedDataReadiness):
        raise PlanContractError("derived_data must be DerivedDataReadiness")
    boot = bool(needs_simulator and (simulator is None or not simulator.booted))
    build = not derived_data.can_reuse
    clean = derived_data.requires_clean_rebuild
    if clean:
        mode = "clean-rebuild"
    elif build:
        mode = "cold-build"
    elif needs_simulator and simulator is None:
        mode = "lease-required"
    elif boot:
        mode = "boot-warm"
    else:
        mode = "warm-reuse"
    resources = [derived_data.cache_key]
    if needs_simulator and simulator is not None:
        resources.append(simulator.resource_key)
    return {
        "schema": RUN_COST_SCHEMA,
        "version": PLAN_VERSION,
        "mode": mode,
        "reuse_environment": bool(derived_data.can_reuse and not clean),
        "boot": boot,
        "build": build,
        "must_clean_rebuild": clean,
        "lease_required": bool(needs_simulator and simulator is None),
        "resources": resources,
        "reason": derived_data.reason,
    }


@dataclass(frozen=True)
class PacketRequest:
    """The planner's small input unit; one packet may contain several groups."""

    packet_id: str
    groups: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    simulator: SimulatorLease | None = None
    derived_data: DerivedDataReadiness | None = None
    needs_simulator: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.packet_id, str) or not self.packet_id.strip():
            raise PlanContractError("packet_id must be non-empty")
        object.__setattr__(
            self, "groups", tuple(dict.fromkeys(str(value) for value in self.groups))
        )
        object.__setattr__(
            self,
            "changed_files",
            tuple(_normalise_path(value) for value in self.changed_files),
        )
        if self.simulator is not None:
            object.__setattr__(
                self, "simulator", SimulatorLease.from_mapping(self.simulator)
            )
        if self.derived_data is not None:
            object.__setattr__(
                self,
                "derived_data",
                DerivedDataReadiness.from_mapping(self.derived_data),
            )
        if self.needs_simulator is not None and not isinstance(
            self.needs_simulator, bool
        ):
            raise PlanContractError("needs_simulator must be boolean or None")


def _coerce_packet(value: PacketRequest | Mapping[str, Any]) -> PacketRequest:
    if isinstance(value, PacketRequest):
        return value
    if not isinstance(value, Mapping):
        raise PlanContractError("resource plan packets must be PacketRequest mappings")
    return PacketRequest(
        packet_id=str(value.get("packet_id", value.get("id", ""))),
        groups=tuple(value.get("groups", ())),
        changed_files=tuple(value.get("changed_files", ())),
        simulator=value.get("simulator"),
        derived_data=value.get("derived_data"),
        needs_simulator=value.get("needs_simulator"),
    )


def build_resource_plan(
    packets: Iterable[PacketRequest | Mapping[str, Any]],
    *,
    root: str | Path | None = None,
    topology: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce a serial execution plan with simulator/build work deduplicated."""

    requests = [_coerce_packet(packet) for packet in packets]
    ids = [request.packet_id for request in requests]
    if len(set(ids)) != len(ids):
        raise PlanContractError("packet_id values must be unique")
    topo = dict(topology or build_topology(root))
    group_map = {str(group["name"]): group for group in topo.get("groups", [])}
    resources: dict[str, dict[str, Any]] = {}
    packet_payloads: list[dict[str, Any]] = []
    simulator_boots = 0
    derived_data_builds = 0
    clean_rebuilds = 0
    readiness_states: dict[str, str] = {}

    for request in requests:
        groups = list(request.groups)
        impact: dict[str, Any] | None = None
        if not groups and request.changed_files:
            impact = select_minimal_groups(request.changed_files, topology=topo)
            groups = list(impact["groups"])
        unknown_groups = sorted(set(groups) - set(group_map))
        if unknown_groups:
            raise PlanContractError(
                f"unknown runner groups: {', '.join(unknown_groups)}"
            )
        group_resources = {
            resource
            for group in groups
            for resource in group_map[group].get("resources", [])
        }
        needs_simulator = (
            request.needs_simulator
            if request.needs_simulator is not None
            else bool({"simulator", "simulator-pool"} & group_resources)
        )
        derived_data = request.derived_data
        if derived_data is None:
            derived_data = (
                DerivedDataReadiness.missing(f"{request.packet_id}-derived-data")
                if "derived-data" in group_resources
                else DerivedDataReadiness.ready(f"{request.packet_id}-no-derived-data")
            )
        run_cost = decide_run_cost(
            simulator=request.simulator,
            derived_data=derived_data,
            needs_simulator=needs_simulator,
        )
        packet_resources: list[str] = []

        if needs_simulator:
            sim_key = (
                request.simulator.resource_key
                if request.simulator
                else (f"simulator:lease-required:{request.packet_id}")
            )
            packet_resources.append(sim_key)
            sim_resource = resources.setdefault(
                sim_key,
                {
                    "kind": "simulator",
                    "resource_key": sim_key,
                    "packets": [],
                    "exclusive": True,
                    "action": "lease-required"
                    if request.simulator is None
                    else ("reuse" if request.simulator.booted else "boot-once"),
                    "boot_count": 0,
                },
            )
            sim_resource["packets"].append(request.packet_id)
            if request.simulator is not None and not sim_resource["boot_count"]:
                sim_resource["boot_count"] = 0 if request.simulator.booted else 1
                simulator_boots += sim_resource["boot_count"]
            elif request.simulator is None and len(sim_resource["packets"]) == 1:
                sim_resource["lease_required"] = True
            if len(sim_resource["packets"]) > 1 and run_cost["boot"]:
                run_cost = dict(run_cost)
                run_cost["boot"] = False
                if run_cost["mode"] == "boot-warm":
                    run_cost["mode"] = "warm-reuse"
                    run_cost["reason"] = (
                        "simulator boot is shared with an earlier packet"
                    )

        if "derived-data" in group_resources:
            prior_status = readiness_states.get(derived_data.cache_key)
            if prior_status is not None and prior_status != derived_data.status:
                raise PlanContractError(
                    "conflicting readiness states for shared DerivedData cache "
                    f"{derived_data.cache_key!r}: {prior_status!r} vs "
                    f"{derived_data.status!r}"
                )
            readiness_states[derived_data.cache_key] = derived_data.status
            dd_key = f"derived-data:{derived_data.cache_key}"
            packet_resources.append(dd_key)
            dd_resource = resources.setdefault(
                dd_key,
                {
                    "kind": "derived-data",
                    "resource_key": dd_key,
                    "cache_key": derived_data.cache_key,
                    "packets": [],
                    "exclusive": True,
                    "action": "reuse"
                    if derived_data.can_reuse
                    else (
                        "clean-rebuild-once"
                        if derived_data.requires_clean_rebuild
                        else "build-once"
                    ),
                    "build_count": 0,
                    "clean_rebuild_count": 0,
                },
            )
            dd_resource["packets"].append(request.packet_id)
            if not dd_resource["build_count"] and not derived_data.can_reuse:
                dd_resource["build_count"] = 1
                dd_resource["clean_rebuild_count"] = int(
                    derived_data.requires_clean_rebuild
                )
                derived_data_builds += 1
                clean_rebuilds += dd_resource["clean_rebuild_count"]
            elif len(dd_resource["packets"]) > 1 and run_cost["build"]:
                run_cost = dict(run_cost)
                run_cost["build"] = False
                run_cost["must_clean_rebuild"] = False
                run_cost["reuse_environment"] = True
                run_cost["mode"] = "warm-reuse"
                run_cost["reason"] = (
                    "DerivedData build is shared with an earlier packet"
                )

        packet_payload = {
            "packet_id": request.packet_id,
            "groups": groups,
            "changed_files": list(request.changed_files),
            "resources": packet_resources,
            "run_cost": run_cost,
        }
        if impact is not None:
            packet_payload["impact"] = impact
        packet_payloads.append(packet_payload)

    summary = {
        "packet_count": len(requests),
        "simulator_boots": simulator_boots,
        "derived_data_builds": derived_data_builds,
        "clean_rebuilds": clean_rebuilds,
    }
    return {
        "schema": RESOURCE_PLAN_SCHEMA,
        "version": PLAN_VERSION,
        "packets": packet_payloads,
        "resources": resources,
        "execution_order": ids,
        "summary": summary,
        "deduplication": {
            "simulator_boots_saved": max(
                0,
                sum(
                    1
                    for packet in packet_payloads
                    if any(
                        str(key).startswith("simulator:") for key in packet["resources"]
                    )
                )
                - simulator_boots,
            ),
            "derived_data_builds_saved": max(
                0,
                sum(
                    1
                    for packet in packet_payloads
                    if any(
                        str(key).startswith("derived-data:")
                        for key in packet["resources"]
                    )
                )
                - derived_data_builds,
            ),
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument(
        "--topology", action="store_true", help="emit the full runner topology"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON (the default output)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = (
        build_topology(args.root)
        if args.topology
        else select_minimal_groups(args.changed_file, root=args.root)
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
