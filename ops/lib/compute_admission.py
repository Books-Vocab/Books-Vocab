"""Structured host admission policy for the canonical compute worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AdmissionError(ValueError):
    """A request is not safe to admit."""


@dataclass(frozen=True)
class HostAdmission:
    host_id: str
    host_role: str


def admit(policy: dict[str, Any]) -> HostAdmission:
    if not isinstance(policy, dict):
        raise AdmissionError("policy-schema")
    if policy.get("host_role") != "felix" or not isinstance(policy.get("host_id"), str):
        raise AdmissionError("host-role")
    health = policy.get("health")
    expected_health = {"healthy": True, "deploy_lock": False, "backup_active": False, "reconcile_active": False}
    if health != expected_health:
        if isinstance(health, dict) and health.get("deploy_lock"):
            raise AdmissionError("deploy-lock")
        raise AdmissionError("health")
    sandbox = policy.get("sandbox")
    expected_sandbox = {"network": "none", "read_only_rootfs": True, "non_root": True, "cap_drop": ["ALL"], "no_new_privileges": True}
    if sandbox != expected_sandbox:
        raise AdmissionError("sandbox")
    return HostAdmission(policy["host_id"], "felix")

