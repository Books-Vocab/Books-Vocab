from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate_cost_reuse as reuse

ISSUED = "2026-08-18T14:00:00Z"
EXPIRES = "2026-08-18T15:00:00Z"
NOW = datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc)


def _identity(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "head": "a" * 40,
        "base": "b" * 40,
        "changed_files": ["ops/gate_cost_reuse.py", "ops/tests/test_gate_cost_reuse.py"],
        "command": ["uv", "run", "pytest", "-q"],
        "test_definition": {"files": ["ops/tests/test_gate_cost_reuse.py"]},
        "fixture": {"files": []},
        "toolchain": {"python": "3.13.7", "uv": "0.8.14"},
        "scope": {"files": [{"path": "ops/gate_cost_reuse.py", "operation": "add"}]},
        "tier": "S1",
        "issued_at": ISSUED,
        "expires_at": EXPIRES,
    }
    values.update(overrides)
    return reuse.build_reuse_identity(**values)


def _previous(identity: dict[str, object], verdict: str = "pass") -> dict[str, object]:
    return reuse.build_reuse_verdict(identity, verdict=verdict)


def test_identity_contains_all_exact_reuse_inputs() -> None:
    identity = _identity()

    assert identity["schema"] == reuse.IDENTITY_SCHEMA
    assert identity["head"] == "a" * 40
    assert identity["base"] == "b" * 40
    for field in (
        "changed_file_digest",
        "command_digest",
        "test_definition_digest",
        "fixture_digest",
        "identity_digest",
    ):
        assert len(identity[field]) == 64
    assert identity["toolchain"] == {"python": "3.13.7", "uv": "0.8.14"}
    assert identity["scope"]["files"][0]["operation"] == "add"
    assert identity["tier"] == "S1"
    assert identity["issued_at"] == ISSUED
    assert identity["expires_at"] == EXPIRES


def test_matching_pass_contract_is_reusable() -> None:
    identity = _identity()

    result = reuse.evaluate_reuse(_previous(identity), identity, now=NOW)

    assert result["reuse"] is True
    assert result["reason_code"] == "identity-match"
    assert result["contract_ready"] is True
    assert result["runner_connected"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("head", "c" * 40, "head-drift"),
        ("base", "d" * 40, "base-drift"),
        ("command", ["uv", "run", "pytest", "-x"], "command-drift"),
        ("changed_files", ["ops/other.py"], "changed-file-drift"),
        ("test_definition", {"files": ["ops/tests/other.py"]}, "test-definition-drift"),
        ("fixture", {"files": ["ops/fixtures/other.json"]}, "fixture-drift"),
        ("toolchain", {"python": "3.14.0", "uv": "0.8.14"}, "toolchain-drift"),
        ("scope", {"files": [{"path": "ops/other.py", "operation": "modify"}]}, "scope-drift"),
        ("tier", "S2", "tier-drift"),
    ],
)
def test_any_exact_identity_drift_disables_reuse(
    field: str, value: object, reason: str,
) -> None:
    previous_identity = _identity()
    current_values = {field: value}
    current_identity = _identity(**current_values)

    result = reuse.evaluate_reuse(
        _previous(previous_identity), current_identity, now=NOW,
    )

    assert result["reuse"] is False
    assert result["reason_code"] == reason


def test_expired_previous_identity_is_stale() -> None:
    previous = _identity(expires_at="2026-08-18T14:30:00Z")
    current = _identity()

    result = reuse.evaluate_reuse(_previous(previous), current, now=NOW)

    assert result["reuse"] is False
    assert result["reason_code"] == "stale"


def test_warn_verdict_is_never_reused_even_when_identity_matches() -> None:
    identity = _identity()

    result = reuse.evaluate_reuse(
        _previous(identity, verdict="warn"), identity, now=NOW,
    )

    assert result["reuse"] is False
    assert result["reason_code"] == "warn-not-reusable"


def test_missing_previous_verdict_is_fail_closed() -> None:
    identity = _identity()

    result = reuse.evaluate_reuse(
        {"identity": identity}, identity, now=NOW,
    )

    assert result["reuse"] is False
    assert result["reason_code"] == "missing-verdict"


@pytest.mark.parametrize("previous", [None, {}, {"identity": {}}])
def test_missing_previous_identity_is_explicitly_false(
    previous: object,
) -> None:
    result = reuse.evaluate_reuse(previous, _identity(), now=NOW)

    assert result["reuse"] is False
    assert result["reason_code"] == "missing"


def test_verdict_has_manager_wiring_follow_up_without_claiming_connection() -> None:
    result = reuse.build_reuse_verdict(_identity(), verdict="pass")

    assert result["contract_ready"] is True
    assert result["runner_connected"] is False
    assert result["wiring_follow_up"] == {
        "owner": "manager",
        "next_step": (
            "connect reuse result through the existing fingerprint and "
            "execution-plan path plus central runner after this ticket lands"
        ),
        "files": ["existing-fingerprint", "existing-execution-plan", "central-runner"],
    }


def test_verdict_is_json_serializable_without_raw_command_or_fixture_inputs() -> None:
    result = reuse.build_reuse_verdict(_identity(), verdict="pass")

    encoded = json.dumps(result, sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["identity"]["command_digest"]
    assert "command" not in decoded["identity"]
    assert "fixture" not in decoded["identity"]


def test_invalid_ttl_is_rejected() -> None:
    with pytest.raises(reuse.ReuseContractError, match="expires_at"):
        _identity(expires_at=ISSUED)
