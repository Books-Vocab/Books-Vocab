from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import worktree_gate_tiers as tiers  # noqa: E402


def _gate(name: str, **extra: object) -> dict[str, object]:
    return {"name": name, "category": "test", "kind": "internal", **extra}


def test_tier_vocabulary_is_closed_and_normalized() -> None:
    assert tiers.normalize_gate_tier(None) == "S2"
    assert tiers.normalize_gate_tier("s1") == "S1"
    with pytest.raises(tiers.GateTierError):
        tiers.normalize_gate_tier("S5")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ui-quality-fast", "S0"),
        ("coverage", "S0"),
        ("ios-build", "S1"),
        ("ios-test-ui:ReviewFlowTests", "S1"),
        ("ios-test-unit", "S2"),
        ("ios-build-catalyst", "S3"),
    ],
)
def test_existing_gate_families_map_to_delivery_tiers(name: str, expected: str) -> None:
    assert tiers.classify_gate_tier(_gate(name)) == expected


def test_whole_ops_fallback_is_more_expensive_than_targeted_ops_test() -> None:
    targeted = _gate("ops-pytest", cmd=["pytest", "ops/tests/test_x.py"])
    focused = _gate("ops-pytest-focused", cmd=["pytest", "ops/tests/test_x.py"])
    whole = _gate("ops-pytest", cmd=["pytest", "ops/tests"])
    assert tiers.classify_gate_tier(targeted) == "S1"
    assert tiers.classify_gate_tier(focused) == "S1"
    assert tiers.classify_gate_tier(whole) == "S2"


def test_select_plan_returns_executed_and_explicitly_deferred_checks() -> None:
    plan = tiers.annotate_plan([
        _gate("static"),
        _gate("ios-build"),
        _gate("ios-test-unit"),
        _gate("ios-build-catalyst"),
    ])
    selected, deferred = tiers.select_plan(plan, "S2")
    assert [item["name"] for item in selected] == ["static", "ios-build", "ios-test-unit"]
    assert [item["name"] for item in deferred] == ["ios-build-catalyst"]


def test_s4_is_an_explicit_release_profile_and_has_no_deferrable_gate() -> None:
    release = tiers.release_gate_plan()
    assert release
    assert {item["tier"] for item in release} == {"S4"}
    assert {item["name"] for item in release} == {
        "release-backend-full",
        "release-ops-full",
        "release-ios-all-targets",
        "release-ios-readiness",
    }
    for item in release:
        allowed, _reason = tiers.deferral_allowed(item, "low")
        assert allowed is False


@pytest.mark.parametrize(
    ("gate_tier", "severity", "allowed"),
    [("S0", "low", False), ("S1", "med", False), ("S2", "low", True),
     ("S3", "med", True), ("S4", "low", False), ("S2", "high", False)],
)
def test_only_named_non_high_s2_s3_failures_can_be_deferred(
    gate_tier: str, severity: str, allowed: bool,
) -> None:
    ok, _reason = tiers.deferral_allowed(_gate("module-regression", tier=gate_tier), severity)
    assert ok is allowed


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["README.md"], "S0"),
        (["docs/sop/release.md"], "S0"),
        (["ops/worktree_orchestrate.py"], "S2"),
        (["ios/App.swift", "backend/src/kg/app.py"], "S3"),
    ],
)
def test_required_cutover_tier_comes_from_scope(files: list[str], expected: str) -> None:
    assert tiers.required_cutover_tier(files) == expected
