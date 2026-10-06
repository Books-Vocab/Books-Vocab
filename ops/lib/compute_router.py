"""Pure local/felix routing decision for compute profiles.

No I/O, no clock reads and no probes happen here: callers inject the observed
local/Felix state and the clock.  Anything unknown, stale or unsafe resolves to
``local`` for ``auto`` and to a named refusal for explicit ``felix``.
"""

from __future__ import annotations

import statistics
from typing import Any

TARGETS = ("auto", "local", "felix")
PROBE_MAX_AGE_SECONDS = 60.0


class RouterError(ValueError):
    """Explicit felix was requested but a safety check refused it."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = sorted(set(reasons))
        super().__init__(",".join(self.reasons))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _safety_reasons(
    *,
    remote_eligible: bool,
    local: dict[str, Any],
    felix: dict[str, Any] | None,
    now: float,
) -> list[str]:
    """Checks no target choice may bypass (shared by auto and explicit felix)."""

    reasons: list[str] = []
    if remote_eligible is not True:
        reasons.append("remote-ineligible")
    if local.get("clean") is not True:
        reasons.append("dirty-source")
    if local.get("missing_capabilities"):
        reasons.append("missing-capability")
    if not isinstance(felix, dict):
        reasons.append("probe-unknown")
        return reasons
    observed = felix.get("observed_at")
    if not _number(observed):
        reasons.append("probe-unknown")
    elif now - observed > PROBE_MAX_AGE_SECONDS or observed > now + 1:
        reasons.append("probe-stale")
    if felix.get("reachable") is not True:
        reasons.append("felix-unreachable")
    if felix.get("host_role") != "felix":
        reasons.append("host-role")
    host_id = felix.get("host_id")
    if not isinstance(host_id, str) or not host_id:
        reasons.append("probe-unknown")
    elif host_id == local.get("host_id"):
        reasons.append("same-host")
    for key, reason in (
        ("admitted", "admission-denied"),
        ("runner_verified", "runner-unverified"),
        ("sandbox_ok", "sandbox-failed"),
        ("production_healthy", "production-unhealthy"),
        ("receipt_key_pinned", "receipt-key-unpinned"),
    ):
        if felix.get(key) is not True:
            reasons.append(reason)
    return reasons


def _result(
    requested: str, target: str, reasons: list[str], savings: float | None = None
) -> dict[str, Any]:
    return {
        "requested": requested,
        "target": target,
        "reasons": sorted(set(reasons)),
        "net_savings_seconds": savings,
    }


def decide(
    *,
    requested: str,
    remote_eligible: bool,
    minimum_remote_seconds: int | None,
    local: dict[str, Any],
    felix: dict[str, Any] | None,
    history: list[float] | None,
    now: float,
) -> dict[str, Any]:
    if requested not in TARGETS:
        raise RouterError(["unknown-target"])
    if requested == "local":
        return _result(requested, "local", ["explicit-local"])
    reasons = _safety_reasons(
        remote_eligible=remote_eligible, local=local, felix=felix, now=now
    )
    if requested == "felix":
        if reasons:
            raise RouterError(reasons)
        return _result(requested, "felix", ["explicit-felix"])

    if local.get("busy") is False:
        reasons.append("local-not-busy")
    elif local.get("busy") is not True or not _number(local.get("slowdown")):
        reasons.append("local-load-unknown")
    if isinstance(felix, dict):
        for key in ("warmup_seconds", "transfer_seconds"):
            if not _number(felix.get(key)):
                reasons.append("probe-unknown")
    samples = [h for h in (history or []) if _number(h)]
    if not samples:
        reasons.append("no-history")
    if reasons:
        return _result(requested, "local", reasons)
    estimate = statistics.median(samples)
    if minimum_remote_seconds is None or estimate < minimum_remote_seconds:
        return _result(requested, "local", ["below-minimum-remote-seconds"])
    assert isinstance(felix, dict)
    savings = estimate * local["slowdown"] - (
        estimate + felix["warmup_seconds"] + felix["transfer_seconds"]
    )
    if savings <= 0:
        return _result(requested, "local", ["not-profitable"], savings)
    return _result(requested, "felix", ["remote-profitable"], savings)
