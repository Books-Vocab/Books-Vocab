"""Pure role, work-mode, and landing-authority contracts for KG delivery.

This module contains no git, registry, or process I/O.  Callers use it to keep
the child admission rules and the Manager-only landing rules identical across
the registry and orchestrator entry points.
"""

from __future__ import annotations

from typing import Any

WORK_MODES = (
    "direct-assignment",
    "ticket-factory",
    "ticket-delivery",
)
OPERATOR_ROLES = ("manager", "integrator")


def validate_work_mode(
    work_mode: str | None,
    *,
    has_scope: bool,
    has_ticket_claim: bool,
    has_campaign: bool = False,
) -> str | None:
    """Return a named admission error, or ``None`` for a valid mode.

    ``None`` is the legacy mode.  It remains readable and writable so old
    registry records can finish their lifecycle; new orchestrator births pass a
    concrete mode and therefore get the stricter contract.
    """
    if work_mode is None:
        return None
    if work_mode not in WORK_MODES:
        return f"unknown work mode: {work_mode!r}"
    if work_mode in {"direct-assignment", "ticket-factory"}:
        if has_ticket_claim or has_campaign:
            return f"{work_mode} cannot claim delivery tickets"
        if not has_scope:
            return f"{work_mode} requires a structured Scope before work begins"
        return None
    if not has_ticket_claim and not has_campaign:
        return "ticket-delivery requires a backlog or campaign claim"
    if has_scope:
        return "ticket-delivery Scope is owned by its tickets, not a direct Scope"
    return None


def operator_refusal(
    *,
    command: str,
    operator: str | None,
    commit: bool,
    manager_only: bool = False,
    integrator_staging: bool = False,
) -> dict[str, Any] | None:
    """Return a structured refusal for an under-specified operator call.

    Dry-runs remain available to every role.  Mutating staging is an Integrator
    operation; mutating landing/backup is a Manager operation.  The CLI flag is
    an explicit authorization attestation, not an identity system.
    """
    if not commit:
        return None
    if manager_only and operator != "manager":
        return {
            "refusal": "manager-only",
            "command": command,
            "operator": operator,
            "required_operator": "manager",
        }
    if integrator_staging and operator not in {"manager", "integrator"}:
        return {
            "refusal": "operator-required",
            "command": command,
            "operator": operator,
            "allowed_operators": ["manager", "integrator"],
        }
    return None


def is_manager(operator: str | None) -> bool:
    return operator == "manager"


def is_integrator(operator: str | None) -> bool:
    return operator == "integrator"
