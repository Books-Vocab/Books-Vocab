from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib import worktree_orchestrator_gate as MODULE


def test_manager_can_adjudicate_an_explicit_non_critical_failure() -> None:
    result = MODULE.adjudicate_gate(
        [
            {
                "name": "routine-ops-check",
                "status": "block",
                "criticality": "non-critical",
            }
        ],
        operator="manager",
    )

    assert result["verdict"] == "warn"
    assert result["adjudicated"] is True
    assert result["non_critical"] == ["routine-ops-check"]
    assert result["critical"] == []


def test_manager_cannot_downgrade_a_critical_failure() -> None:
    result = MODULE.adjudicate_gate(
        [{"name": "security-check", "status": "block", "criticality": "critical"}],
        operator="manager",
    )

    assert result["verdict"] == "block"
    assert result["adjudicated"] is True
    assert result["critical"] == ["security-check"]
    assert result["non_critical"] == []


def test_only_manager_can_commit_an_adjudication() -> None:
    result = MODULE.adjudicate_gate(
        [
            {
                "name": "routine-ops-check",
                "status": "block",
                "criticality": "non-critical",
            }
        ],
        operator="worker",
        commit=True,
    )

    assert result["verdict"] == "block"
    assert result["adjudicated"] is False
    assert result["refusal"] == {
        "refusal": "manager-only",
        "command": "gate",
        "operator": "worker",
        "required_operator": "manager",
    }


def test_non_manager_can_preview_without_creating_a_verdict() -> None:
    result = MODULE.adjudicate_gate(
        [
            {
                "name": "routine-ops-check",
                "status": "block",
                "criticality": "non-critical",
            }
        ],
        operator="worker",
        commit=False,
    )

    assert result["verdict"] == "warn"
    assert result["adjudicated"] is False
    assert "refusal" not in result


@pytest.mark.parametrize(
    "result",
    [
        {"name": "unknown-status", "status": "timeout", "criticality": "non-critical"},
        {"name": "unknown-criticality", "status": "block", "criticality": "routine"},
        {"name": "missing-criticality", "status": "block"},
    ],
)
def test_unreadable_gate_metadata_fails_closed(result: dict[str, object]) -> None:
    adjudication = MODULE.adjudicate_gate([result], operator="manager")

    assert adjudication["verdict"] == "block"
    assert adjudication["adjudicated"] is True
    assert adjudication["critical"] == []
    assert adjudication["non_critical"] == []
    assert adjudication["reasons"]


def test_aggregate_verdict_keeps_the_legacy_string_projection() -> None:
    assert (
        MODULE.aggregate_verdict([{"status": "block", "criticality": "non-critical"}])
        == "warn"
    )
