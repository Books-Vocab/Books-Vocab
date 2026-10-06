"""Pure Manager adjudication for worktree Gate results.

The local orchestrator owns execution and persistence.  This module only applies
the closed verdict policy, so callers can test the Manager/non-critical boundary
without starting a process or touching Git, the registry, or a worktree.

An explicit ``criticality`` marker is required for a failing result.  A
non-critical ``block`` or ``inconclusive`` result may be recorded as ``warn`` by
the Manager; critical or unreadable results remain ``block``.  A mutating
adjudication is Manager-only, while previews remain available to every operator.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

GATE_ADJUDICATION_SCHEMA = "kg.worktree.gate.adjudication.v1"
GATE_STATUSES = ("pass", "warn", "block", "inconclusive")
CRITICALITIES = ("critical", "non-critical")
MANAGER_OPERATOR = "manager"


def operator_refusal(
    *,
    command: str,
    operator: str | None,
    commit: bool,
    manager_only: bool = False,
) -> dict[str, Any] | None:
    """Return a structured refusal when a committed operation lacks authority."""

    if not commit or not manager_only or operator == MANAGER_OPERATOR:
        return None
    return {
        "refusal": "manager-only",
        "command": command,
        "operator": operator,
        "required_operator": MANAGER_OPERATOR,
    }


def _normalise_criticality(value: object) -> str | None:
    if value in CRITICALITIES:
        return str(value)
    if type(value) is bool:
        return "critical" if value else "non-critical"
    return None


def _result_name(result: Mapping[str, object], index: int) -> str:
    value = result.get("name")
    return (
        value.strip() if isinstance(value, str) and value.strip() else f"gate-{index}"
    )


def _normalise_result(
    result: object, index: int
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(result, Mapping):
        return None, [f"gate-{index}: result must be an object"]

    name = _result_name(result, index)
    raw_status = result.get("status")
    if not isinstance(raw_status, str) or raw_status not in GATE_STATUSES:
        return None, [f"{name}: unknown status {raw_status!r}"]

    raw_criticality = result.get("criticality")
    criticality = _normalise_criticality(raw_criticality)
    if raw_criticality is not None and criticality is None:
        return None, [f"{name}: unknown criticality {raw_criticality!r}"]
    if raw_status in {"block", "inconclusive"} and criticality is None:
        return None, [f"{name}: failing result must declare criticality"]

    effective_status = raw_status
    if raw_status in {"block", "inconclusive"}:
        effective_status = "warn" if criticality == "non-critical" else "block"

    normalised: dict[str, Any] = {
        "name": name,
        "status": raw_status,
        "effective_status": effective_status,
    }
    if criticality is not None:
        normalised["criticality"] = criticality
    return normalised, []


def adjudicate_gate(
    results: Iterable[object],
    *,
    operator: str | None = MANAGER_OPERATOR,
    commit: bool = True,
) -> dict[str, Any]:
    """Return the machine-readable Manager adjudication for ``results``.

    ``commit`` is an authority boundary, not a persistence operation in this
    pure module.  It represents whether the caller intends to create the Gate
    verdict.  Non-Manager committed calls are refused and fail closed without
    evaluating a potentially misleading downgrade.
    """

    refusal = operator_refusal(
        command="gate",
        operator=operator,
        commit=commit,
        manager_only=True,
    )
    if refusal is not None:
        return {
            "schema": GATE_ADJUDICATION_SCHEMA,
            "operator": operator,
            "commit": commit,
            "adjudicated": False,
            "verdict": "block",
            "critical": [],
            "non_critical": [],
            "results": [],
            "reasons": ["only Manager may create a Gate verdict"],
            "refusal": refusal,
        }

    normalised_results: list[dict[str, Any]] = []
    reasons: list[str] = []
    critical: list[str] = []
    non_critical: list[str] = []

    for index, raw_result in enumerate(results):
        normalised, problems = _normalise_result(raw_result, index)
        if problems:
            reasons.extend(problems)
            continue
        assert normalised is not None
        normalised_results.append(normalised)
        if normalised["status"] in {"block", "inconclusive"}:
            if normalised.get("criticality") == "critical":
                critical.append(normalised["name"])
            elif normalised.get("criticality") == "non-critical":
                non_critical.append(normalised["name"])

    if reasons:
        verdict = "block"
    else:
        statuses = {item["effective_status"] for item in normalised_results}
        if "block" in statuses:
            verdict = "block"
        elif "warn" in statuses:
            verdict = "warn"
        else:
            verdict = "pass"

    return {
        "schema": GATE_ADJUDICATION_SCHEMA,
        "operator": operator,
        "commit": commit,
        "adjudicated": commit,
        "verdict": verdict,
        "critical": sorted(critical),
        "non_critical": sorted(non_critical),
        "results": normalised_results,
        "reasons": reasons,
    }


def aggregate_verdict(results: Iterable[object]) -> str:
    """Return the legacy string projection without creating a Gate verdict."""

    return str(
        adjudicate_gate(results, operator=MANAGER_OPERATOR, commit=False)["verdict"]
    )
