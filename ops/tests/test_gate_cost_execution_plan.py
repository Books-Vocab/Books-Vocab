from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

import gate_cost_execution_plan as plan


def test_topology_is_machine_readable_and_covers_current_runner_groups() -> None:
    topology = plan.build_topology(ROOT)

    assert topology["schema"] == "kg.gate.test-topology.v1"
    assert topology["runner"] == "ops/test_ops.sh"
    assert topology["groups"]
    groups = {group["name"]: group for group in topology["groups"]}

    assert {
        "worktree-orchestrator",
        "ios-ops",
        "ios-device-lock",
        "asc",
    } <= groups.keys()
    assert topology["default_groups"]
    assert "asc" in topology["optional_groups"]
    assert all(group["command"] for group in groups.values())
    assert all(group["responsibility"] for group in groups.values())


def test_changed_file_impact_selects_only_the_smallest_ops_group() -> None:
    decision = plan.select_minimal_groups(["ops/lib/ios_lock_wait.sh"], root=ROOT)

    assert decision["schema"] == "kg.gate.group-impact.v1"
    assert decision["groups"] == ["ios-device-lock"]
    assert decision["unmatched"] == []
    assert decision["groups"] != ["ops-ci-coverage"]


def test_existing_runner_test_path_wins_over_secondary_profile_metadata() -> None:
    decision = plan.select_minimal_groups(
        ["ops/tests/test_ios_xctestrun_cache.sh"], root=ROOT
    )

    assert decision["groups"] == ["ios-ops"]


def test_runner_change_routes_to_coverage_contract_without_running_every_group() -> (
    None
):
    decision = plan.select_minimal_groups(["ops/test_ops.sh"], root=ROOT)

    assert decision["groups"] == ["ops-ci-coverage"]
    assert any("aggregate runner" in reason for reason in decision["reasons"])


def test_non_ops_change_does_not_fall_back_to_expensive_ops_suite() -> None:
    decision = plan.select_minimal_groups(
        ["docs/sop/ios.md", "backend/src/kg/api.py"], root=ROOT
    )

    assert decision["groups"] == []
    assert decision["unmatched"] == ["backend/src/kg/api.py", "docs/sop/ios.md"]
    assert decision["fallback"] is False


def test_simulator_lease_has_stable_key_and_owner_guard() -> None:
    lease = plan.SimulatorLease(
        pool="kg-pool-1",
        udid="SIM-001",
        runtime="iOS-18-5",
        device_type="iPhone 16",
        owner="packet-a",
    )

    assert lease.resource_key == "simulator:SIM-001:iOS-18-5"
    assert lease.can_release("packet-a") is True
    assert lease.can_release("packet-b") is False
    assert lease.to_dict()["schema"] == "kg.ios.simulator-lease.v1"
    assert plan.SimulatorLease.from_mapping(lease.to_dict()) == lease


def test_derived_data_readiness_distinguishes_reuse_missing_and_clean_rebuild() -> None:
    warm = plan.DerivedDataReadiness.assess(
        cache_key="ios-debug-abc",
        path=".cache/ios-test-derived-data/ios-debug-abc",
        exists=True,
        ready_marker=True,
        actual_head="a" * 40,
        expected_head="a" * 40,
        actual_definition_digest="d1",
        expected_definition_digest="d1",
    )
    missing = plan.DerivedDataReadiness.assess(
        cache_key="ios-debug-missing",
        path=".cache/ios-test-derived-data/ios-debug-missing",
        exists=False,
        ready_marker=False,
        actual_head=None,
        expected_head="a" * 40,
        actual_definition_digest=None,
        expected_definition_digest="d1",
    )
    stale = plan.DerivedDataReadiness.assess(
        cache_key="ios-debug-stale",
        path=".cache/ios-test-derived-data/ios-debug-stale",
        exists=True,
        ready_marker=True,
        actual_head="b" * 40,
        expected_head="a" * 40,
        actual_definition_digest="d1",
        expected_definition_digest="d1",
    )

    assert warm.status == "ready"
    assert warm.can_reuse is True
    assert warm.requires_clean_rebuild is False
    assert missing.status == "missing"
    assert missing.can_reuse is False
    assert missing.requires_clean_rebuild is False
    assert stale.status == "stale-head"
    assert stale.can_reuse is False
    assert stale.requires_clean_rebuild is True
    assert plan.DerivedDataReadiness.from_mapping(warm.to_dict()) == warm


def test_run_cost_separates_boot_reuse_cold_build_and_clean_rebuild() -> None:
    lease = plan.SimulatorLease(
        pool="kg-pool-1",
        udid="SIM-001",
        runtime="iOS-18-5",
        device_type="iPhone 16",
        owner="packet-a",
        booted=True,
    )
    ready = plan.DerivedDataReadiness.ready("ios-debug-abc")
    missing = plan.DerivedDataReadiness.missing("ios-debug-missing")
    stale = plan.DerivedDataReadiness.clean_rebuild(
        "ios-debug-stale", reason="definition-changed"
    )

    warm = plan.decide_run_cost(
        simulator=lease, derived_data=ready, needs_simulator=True
    )
    cold = plan.decide_run_cost(
        simulator=None, derived_data=missing, needs_simulator=False
    )
    rebuild = plan.decide_run_cost(
        simulator=lease, derived_data=stale, needs_simulator=True
    )

    assert warm["mode"] == "warm-reuse"
    assert warm["reuse_environment"] is True
    assert warm["boot"] is False
    assert warm["build"] is False
    assert cold["mode"] == "cold-build"
    assert cold["reuse_environment"] is False
    assert cold["build"] is True
    assert rebuild["mode"] == "clean-rebuild"
    assert rebuild["must_clean_rebuild"] is True
    assert rebuild["build"] is True


def test_unleased_simulator_is_explicitly_not_claimed_as_warm() -> None:
    decision = plan.decide_run_cost(
        simulator=None,
        derived_data=plan.DerivedDataReadiness.ready("ios-debug-abc"),
        needs_simulator=True,
    )

    assert decision["mode"] == "lease-required"
    assert decision["lease_required"] is True


def test_resource_plan_deduplicates_boot_and_build_across_packets() -> None:
    lease = plan.SimulatorLease(
        pool="kg-pool-1",
        udid="SIM-001",
        runtime="iOS-18-5",
        device_type="iPhone 16",
        owner="packet-a",
    )
    ready = plan.DerivedDataReadiness.ready("ios-debug-abc")
    packets = [
        plan.PacketRequest(
            "packet-a", groups=("ios-ops",), simulator=lease, derived_data=ready
        ),
        plan.PacketRequest(
            "packet-b", groups=("ios-ops",), simulator=lease, derived_data=ready
        ),
    ]

    resource_plan = plan.build_resource_plan(packets, root=ROOT)

    assert resource_plan["schema"] == "kg.gate.resource-plan.v1"
    assert resource_plan["summary"] == {
        "packet_count": 2,
        "simulator_boots": 1,
        "derived_data_builds": 0,
        "clean_rebuilds": 0,
    }
    assert resource_plan["resources"]["simulator:SIM-001:iOS-18-5"]["packets"] == [
        "packet-a",
        "packet-b",
    ]
    assert [packet["run_cost"]["mode"] for packet in resource_plan["packets"]] == [
        "boot-warm",
        "warm-reuse",
    ]


def test_resource_plan_rejects_conflicting_readiness_for_one_shared_cache() -> None:
    lease = plan.SimulatorLease(
        pool="kg-pool-1",
        udid="SIM-001",
        runtime="iOS-18-5",
        device_type="iPhone 16",
        owner="packet-a",
    )
    packets = [
        plan.PacketRequest(
            "packet-a",
            groups=("ios-ops",),
            simulator=lease,
            derived_data=plan.DerivedDataReadiness.ready("ios-debug-abc"),
        ),
        plan.PacketRequest(
            "packet-b",
            groups=("ios-ops",),
            simulator=lease,
            derived_data=plan.DerivedDataReadiness.clean_rebuild(
                "ios-debug-abc", reason="definition-changed"
            ),
        ),
    ]

    with pytest.raises(plan.PlanContractError, match="conflicting readiness"):
        plan.build_resource_plan(packets, root=ROOT)


@pytest.mark.parametrize("bad", ["", "not a path"])
def test_changed_file_paths_are_validated(bad: str) -> None:
    with pytest.raises(plan.PlanContractError):
        plan.select_minimal_groups([bad])
