"""RED/contract tests for the versioned compute-profile control plane."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REGISTRY = Path(__file__).resolve().parents[1] / "compute_profiles.yml"
sys.path.insert(0, str(REGISTRY.parent))

from lib.compute_contract import (
    ContractError,
    canonical_spec,
    load_profile_registry,
    resolve_profile,
    spec_digest,
    validate_profile,
)


def test_registry_is_versioned_and_shipped() -> None:
    registry = load_profile_registry(REGISTRY)
    assert registry["schema"] == "kg.compute_profiles.v1"
    assert registry["version"] == 1
    assert set(registry["profiles"]) >= {
        "backend.targeted-pytest",
        "ops.docs-lint-registry",
    }


def test_profile_resolves_literal_argv_and_stable_digest() -> None:
    first = resolve_profile(
        "backend.targeted-pytest",
        {"test_path": "backend/tests/test_ops_edit.py"},
    )
    second = resolve_profile(
        "backend.targeted-pytest",
        {"test_path": "backend/tests/test_ops_edit.py"},
    )
    assert first["argv"][-1] == "backend/tests/test_ops_edit.py"
    assert all(isinstance(arg, str) for arg in first["argv"])
    assert first["shell"] is False
    assert first["spec_digest"] == second["spec_digest"]
    assert len(first["spec_digest"]) == 64
    assert spec_digest(first["spec"]) == first["spec_digest"]
    assert canonical_spec(first["spec"]) == canonical_spec(second["spec"])
    reordered = {"b": 2, "a": 1}
    assert canonical_spec(reordered) == '{"a":1,"b":2}'
    assert spec_digest({"a": 1, "b": 2}) == spec_digest(reordered)
    assert spec_digest({"a": 1, "b": 3}) != spec_digest({"a": 1, "b": 2})
    changed = copy.deepcopy(first["spec"])
    changed["argv"] = [*changed["argv"], "--changed"]
    assert spec_digest(changed) != first["spec_digest"]

    spaced = resolve_profile(
        "backend.targeted-pytest",
        {"test_path": "backend/tests/test ops_edit.py"},
    )
    assert spaced["argv"][-1] == "backend/tests/test ops_edit.py"
    assert spaced["argv"][-1] != "backend/tests/test"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"test_path": "-q"}, "leading-dash"),
        ({"test_path": "backend/../secrets.txt"}, "path-traversal"),
        ({"test_path": "backend/tests/\nnope.py"}, "control-character"),
        ({"test_path": "backend/tests/`id`.py"}, "shell-token"),
        ({"test_path": "backend/tests/$(id).py"}, "shell-token"),
        ({"test_path": "backend/tests/測試.py"}, "non-ascii"),
        ({"test_path": "backend/tests/" + "x" * 300 + ".py"}, "too-long"),
    ],
)
def test_parameter_values_fail_closed(params: dict[str, str], code: str) -> None:
    with pytest.raises(ContractError, match=code):
        resolve_profile("backend.targeted-pytest", params)


def test_unknown_and_extra_parameters_are_named() -> None:
    with pytest.raises(ContractError, match="unknown-profile"):
        resolve_profile("unknown.profile", {})
    with pytest.raises(ContractError, match="extra-parameter"):
        resolve_profile(
            "backend.targeted-pytest",
            {"test_path": "backend/tests/test_ops_edit.py", "env": "x"},
        )


@pytest.mark.parametrize("field", ["cwd", "env", "remote_host"])
def test_raw_top_level_execution_controls_are_rejected(field: str) -> None:
    registry = load_profile_registry(REGISTRY)
    profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
    profile[field] = [] if field == "argv" else False
    with pytest.raises(ContractError, match="forbidden-field"):
        validate_profile(profile, name="backend.targeted-pytest")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [("argv", ["sh", "-c", "id"], "parameter-contract"), ("shell", True, "shell-disabled")],
)
def test_nested_command_controls_are_rejected(field: str, value: object, code: str) -> None:
    registry = load_profile_registry(REGISTRY)
    profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
    profile["command"][field] = value
    with pytest.raises(ContractError, match=code):
        validate_profile(profile, name="backend.targeted-pytest")


def test_dirty_source_and_missing_capability_are_refused() -> None:
    with pytest.raises(ContractError, match="dirty-source"):
        resolve_profile(
            "backend.targeted-pytest",
            {"test_path": "backend/tests/test_ops_edit.py"},
            source_dirty=True,
        )
    with pytest.raises(ContractError, match="missing-capability"):
        resolve_profile(
            "backend.targeted-pytest",
            {"test_path": "backend/tests/test_ops_edit.py"},
            available_capabilities={"bash"},
        )


def test_profile_registry_rejects_production_and_unsafe_contracts() -> None:
    registry = load_profile_registry(REGISTRY)
    profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
    profile["side_effects"] = ["production-write"]
    with pytest.raises(ContractError, match="forbidden-side-effect"):
        validate_profile(profile, name="backend.targeted-pytest")

    profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
    profile["network_policy"] = "internet"
    with pytest.raises(ContractError, match="network-policy"):
        validate_profile(profile, name="backend.targeted-pytest")

    profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
    profile["runner_image_digest"] = None
    with pytest.raises(ContractError, match="runner-image-digest"):
        validate_profile(profile, name="backend.targeted-pytest")

    for effect in [
        "credential-read", "docker-socket", "production-network", "localhost-production",
        "deploy", "migration", "ops-edit", "cutover", "sync", "release",
    ]:
        profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
        profile["side_effects"] = [effect]
        with pytest.raises(ContractError, match="forbidden-side-effect"):
            validate_profile(profile, name="backend.targeted-pytest")

    for field, value, code in [
        ("network_policy", None, "network-policy"),
        ("network_policy", "internet", "network-policy"),
        ("sandbox_policy", None, "invalid-field"),
        ("sandbox_policy", "untrusted", "invalid-field"),
    ]:
        profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
        profile[field] = value
        with pytest.raises(ContractError, match=code):
            validate_profile(profile, name="backend.targeted-pytest")

    profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
    profile["remote_eligible"] = True
    with pytest.raises(ContractError, match="remote-ineligible"):
        validate_profile(profile, name="backend.targeted-pytest")
    profile = copy.deepcopy(registry["profiles"]["backend.targeted-pytest"])
    profile["git_metadata_required"] = True
    with pytest.raises(ContractError, match="git-metadata"):
        validate_profile(profile, name="backend.targeted-pytest")


def test_canonical_spec_is_json_not_shell() -> None:
    spec = {"argv": ["pytest", "a b;$(id)"], "shell": False, "source": "clean"}
    encoded = canonical_spec(spec)
    assert json.loads(encoded) == spec
    assert "\\u0027" not in encoded
    assert "\\u003b" not in encoded
