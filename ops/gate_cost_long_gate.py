#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Machine-readable safety contract for expensive long-running gates.

This module describes a policy boundary for a future central runner.  It does
not start subprocesses, acquire runner locks, or connect to the existing gate
runner.  That separation is deliberate: the contract can be tested and
integrated without claiming that runner wiring already exists.
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

CONTRACT_SCHEMA = "kg.gate.cost-long-gate.v1"
PLAN_SCHEMA = "kg.gate.cost-long-gate-plan.v1"
CONTRACT_VERSION = 1
DEFAULT_RESOURCE_KEY = "ops-python-long-gate"
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 20.0
DEFAULT_STALE_AFTER_SECONDS = 60.0

# Compatibility aliases keep the names discoverable to callers that already
# use the shorter gate-cost vocabulary.
SCHEMA = CONTRACT_SCHEMA
HEARTBEAT_INTERVAL_SECONDS = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
STALE_AFTER_SECONDS = DEFAULT_STALE_AFTER_SECONDS

PROTECTED_GATE_KINDS = frozenset(
    {
        "full",
        "full-gate",
        "release",
        "release-gate",
        "release-full",
        "s4",
    }
)

WIRING_FOLLOW_UP = {
    "owner": "manager",
    "next_step": (
        "connect long-gate policy through the existing central runner after this ticket lands"
    ),
    "files": ["central-runner"],
}

HEARTBEAT_FIELDS = [
    "elapsed",
    "pid",
    "alive",
    "stalled",
    "idle",
    "resource_key",
    "fingerprint",
]


class LongGateContractError(ValueError):
    """Raised when a long-gate policy input is unsafe or ambiguous."""


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LongGateContractError(f"{name} must be a non-empty string")
    return value.strip()


def _seconds(name: str, value: Any, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LongGateContractError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0) or (
        not positive and number < 0
    ):
        comparator = "positive" if positive else "non-negative"
        raise LongGateContractError(f"{name} must be {comparator}")
    return number


def _normalise_gate_kind(value: str) -> str:
    kind = _text("gate_kind", value).lower()
    return kind.replace("_", "-").replace(" ", "-")


def _is_protected_token(value: str) -> bool:
    kind = _normalise_gate_kind(value)
    return kind in PROTECTED_GATE_KINDS or "release" in kind or "full" in kind


def is_protected_gate(
    gate_kind: str = "long-gate",
    *,
    gate_tier: str | None = None,
    release: bool = False,
    full: bool = False,
) -> bool:
    """Return whether a request is release/full protected.

    S4 is treated as protected because it is the release-level tier.  The
    explicit boolean flags are accepted for callers that already have a
    structured gate classification instead of a string kind.
    """

    if release or full or _is_protected_token(gate_kind):
        return True
    return gate_tier is not None and _is_protected_token(gate_tier)


def build_long_gate_contract(
    *,
    resource_key: str = DEFAULT_RESOURCE_KEY,
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    """Build the standalone contract consumed by a future runner adapter."""

    resource = _text("resource_key", resource_key)
    interval = _seconds("heartbeat_interval_seconds", heartbeat_interval_seconds)
    stale_after = _seconds("stale_after_seconds", stale_after_seconds)
    if stale_after < interval:
        raise LongGateContractError(
            "stale_after_seconds must be at least heartbeat_interval_seconds"
        )

    return {
        "schema": CONTRACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "contract_ready": True,
        "runner_connected": False,
        "wiring_follow_up": dict(WIRING_FOLLOW_UP),
        "heartbeat": {
            "required": True,
            "interval_seconds": interval,
            "stale_after_seconds": stale_after,
            "observable": "stderr",
            "fields": list(HEARTBEAT_FIELDS),
        },
        "lane": {
            "name": "independent",
            "independent": True,
            "resource_key": resource,
            "different_fingerprints_may_run_in_parallel": True,
        },
        "coalescing": {
            "enabled": True,
            "key": "fingerprint",
            "same_fingerprint": "reuse",
            "different_fingerprint": "parallel",
            "stale": "fail-closed",
        },
        "protected_gate_policy": {
            "coalesce": False,
            "defer": False,
            "degrade": False,
        },
        "runner": {
            "connected": False,
            "central_runner_untouched": True,
        },
    }


# Short aliases are intentional: the contract is a small standalone seam and
# should not force future callers to depend on one naming style.
build_contract = build_long_gate_contract
long_gate_contract = build_long_gate_contract


def _heartbeat_is_fresh(
    heartbeat_at: Any,
    *,
    now: float,
    stale_after_seconds: float,
) -> bool:
    if heartbeat_at is None or isinstance(heartbeat_at, bool):
        return False
    try:
        last = float(heartbeat_at)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(last) or last > now:
        return False
    return now - last <= stale_after_seconds


def _existing_status(existing: Mapping[str, Any]) -> str:
    status = existing.get("status", "running")
    return _text("existing.status", status).lower().replace("_", "-")


def _base_plan(
    fingerprint: str,
    *,
    gate_kind: str,
    resource_key: str,
    protected: bool,
    stale: bool = False,
) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "version": CONTRACT_VERSION,
        "contract_ready": True,
        "runner_connected": False,
        "wiring_follow_up": dict(WIRING_FOLLOW_UP),
        "fingerprint": fingerprint,
        "gate_kind": gate_kind,
        "resource_key": resource_key,
        "lane": "independent",
        "protected_gate": protected,
        "stale": stale,
        "decision": "run",
        "reason": "new-fingerprint",
        "rerun": True,
        "coalesced": False,
        "parallel_allowed": not protected,
        "deferred": False,
        "degraded": False,
    }


def plan_long_gate(
    fingerprint: str,
    *,
    gate_kind: str = "long-gate",
    gate_tier: str | None = None,
    resource_key: str = DEFAULT_RESOURCE_KEY,
    existing: Mapping[str, Any] | None = None,
    now: float | None = None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    defer: bool = False,
    degrade: bool = False,
    release: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """Return a safe plan without executing a gate.

    ``existing`` is a prior state for the *same* fingerprint.  Different
    fingerprints are intentionally not compared by resource key: the resource
    key names the lane, while the fingerprint names the reusable work.
    """

    fp = _text("fingerprint", fingerprint)
    kind = _normalise_gate_kind(gate_kind)
    resource = _text("resource_key", resource_key)
    stale_after = _seconds("stale_after_seconds", stale_after_seconds)
    current = time.monotonic() if now is None else _seconds("now", now, positive=False)
    protected = is_protected_gate(
        kind,
        gate_tier=gate_tier,
        release=release,
        full=full,
    )
    plan = _base_plan(
        fp,
        gate_kind=kind,
        resource_key=resource,
        protected=protected,
    )

    # A protected gate never trusts an old entry for coalescing.  It always
    # remains a real run, even if a caller asks to defer or degrade it.
    if protected:
        plan["reason"] = "protected-gate"
        return plan

    if existing is not None:
        if not isinstance(existing, Mapping):
            raise LongGateContractError("existing state must be a mapping")
        existing_fingerprint = existing.get("fingerprint")
        if existing_fingerprint is not None:
            existing_fingerprint = _text(
                "existing.fingerprint", existing_fingerprint,
            )
            if existing_fingerprint != fp:
                plan["reason"] = "different-fingerprint"
                return plan
        status = _existing_status(existing)
        if status in {"stale", "expired", "unknown", "inconclusive"}:
            plan.update(
                {
                    "decision": "fail-closed",
                    "reason": "stale-heartbeat",
                    "rerun": False,
                    "parallel_allowed": False,
                    "stale": True,
                }
            )
            return plan
        if status in {"running", "queued", "active", "started"}:
            if not _heartbeat_is_fresh(
                existing.get("heartbeat_at"),
                now=current,
                stale_after_seconds=stale_after,
            ):
                plan.update(
                    {
                        "decision": "fail-closed",
                        "reason": "stale-heartbeat",
                        "rerun": False,
                        "parallel_allowed": False,
                        "stale": True,
                    }
                )
                return plan
            plan.update(
                {
                    "decision": "reuse",
                    "reason": "same-fingerprint",
                    "rerun": False,
                    "coalesced": True,
                    "parallel_allowed": False,
                }
            )
            return plan
        if status in {
            "completed",
            "complete",
            "passed",
            "pass",
            "warn",
            "failed",
            "blocked",
        }:
            plan.update(
                {
                    "decision": "reuse",
                    "reason": "same-fingerprint",
                    "rerun": False,
                    "coalesced": True,
                    "parallel_allowed": False,
                }
            )
            return plan
        plan.update(
            {
                "decision": "fail-closed",
                "reason": "unknown-state",
                "rerun": False,
                "parallel_allowed": False,
                "stale": True,
            }
        )
        return plan

    if degrade:
        plan.update(
            {
                "decision": "fail-closed",
                "reason": "degrade-not-supported",
                "rerun": False,
                "parallel_allowed": False,
            }
        )
        return plan
    if defer:
        plan.update(
            {
                "decision": "defer",
                "reason": "caller-requested-defer",
                "rerun": False,
                "deferred": True,
                "parallel_allowed": False,
            }
        )
        return plan

    return plan


coalescing_decision = plan_long_gate
plan_run = plan_long_gate


class LongGateCoordinator:
    """Thread-safe in-memory policy coordinator for contract tests/adapters.

    It deliberately owns no subprocess or OS lock.  It only records the
    fingerprint/heartbeat facts a future runner must provide.
    """

    def __init__(
        self,
        *,
        resource_key: str = DEFAULT_RESOURCE_KEY,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        contract = build_long_gate_contract(
            resource_key=resource_key,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            stale_after_seconds=stale_after_seconds,
        )
        self.resource_key = contract["lane"]["resource_key"]
        self.heartbeat_interval_seconds = contract["heartbeat"]["interval_seconds"]
        self.stale_after_seconds = contract["heartbeat"]["stale_after_seconds"]
        self._clock = clock
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def request(
        self,
        fingerprint: str,
        *,
        gate_kind: str = "long-gate",
        gate_tier: str | None = None,
        now: float | None = None,
        defer: bool = False,
        degrade: bool = False,
        release: bool = False,
        full: bool = False,
    ) -> dict[str, Any]:
        fp = _text("fingerprint", fingerprint)
        with self._lock:
            current = self._clock() if now is None else now
            existing = self._runs.get(fp)
            plan = plan_long_gate(
                fp,
                gate_kind=gate_kind,
                gate_tier=gate_tier,
                resource_key=self.resource_key,
                existing=existing,
                now=current,
                stale_after_seconds=self.stale_after_seconds,
                defer=defer,
                degrade=degrade,
                release=release,
                full=full,
            )
            if plan["decision"] == "run":
                self._runs[fp] = {
                    "fingerprint": fp,
                    "gate_kind": plan["gate_kind"],
                    "resource_key": self.resource_key,
                    "status": "running",
                    "heartbeat_at": float(current),
                    "phase": "start",
                }
            return plan

    def heartbeat(
        self,
        fingerprint: str,
        *,
        at: float | None = None,
        phase: str = "heartbeat",
    ) -> dict[str, Any]:
        fp = _text("fingerprint", fingerprint)
        current = self._clock() if at is None else _seconds("at", at, positive=False)
        with self._lock:
            record = self._runs.get(fp)
            if record is None:
                raise LongGateContractError(f"unknown fingerprint: {fp}")
            if record["status"] != "running":
                raise LongGateContractError(f"fingerprint is not running: {fp}")
            if current < record["heartbeat_at"]:
                raise LongGateContractError("heartbeat timestamp moved backwards")
            record["heartbeat_at"] = float(current)
            record["phase"] = _text("phase", phase)
            return dict(record)

    def complete(
        self,
        fingerprint: str,
        *,
        outcome: str = "pass",
        at: float | None = None,
    ) -> dict[str, Any]:
        fp = _text("fingerprint", fingerprint)
        current = self._clock() if at is None else _seconds("at", at, positive=False)
        result = _text("outcome", outcome).lower()
        with self._lock:
            record = self._runs.get(fp)
            if record is None:
                raise LongGateContractError(f"unknown fingerprint: {fp}")
            if record["status"] != "running":
                raise LongGateContractError(f"fingerprint is not running: {fp}")
            record.update(
                {
                    "status": "completed",
                    "outcome": result,
                    "completed_at": float(current),
                }
            )
            return dict(record)

    def active_fingerprints(self) -> list[str]:
        with self._lock:
            return sorted(
                fp
                for fp, record in self._runs.items()
                if record["status"] == "running"
            )

    def state(self, fingerprint: str) -> dict[str, Any] | None:
        fp = _text("fingerprint", fingerprint)
        with self._lock:
            record = self._runs.get(fp)
            return None if record is None else dict(record)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON (the default)")
    parser.add_argument("--fingerprint")
    parser.add_argument("--gate-kind", default="long-gate")
    parser.add_argument("--gate-tier")
    parser.add_argument("--resource-key", default=DEFAULT_RESOURCE_KEY)
    parser.add_argument("--now", type=float)
    parser.add_argument("--heartbeat-at", type=float)
    parser.add_argument("--status", default="new")
    parser.add_argument("--stale-after-seconds", type=float, default=DEFAULT_STALE_AFTER_SECONDS)
    parser.add_argument("--defer", action="store_true")
    parser.add_argument("--degrade", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    contract = build_long_gate_contract(
        resource_key=args.resource_key,
        stale_after_seconds=args.stale_after_seconds,
    )
    payload: dict[str, Any] = contract
    if args.fingerprint is not None:
        existing = None
        if args.status != "new":
            existing = {"status": args.status, "heartbeat_at": args.heartbeat_at}
        payload = dict(contract)
        payload["plan"] = plan_long_gate(
            args.fingerprint,
            gate_kind=args.gate_kind,
            gate_tier=args.gate_tier,
            resource_key=args.resource_key,
            existing=existing,
            now=args.now,
            stale_after_seconds=args.stale_after_seconds,
            defer=args.defer,
            degrade=args.degrade,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if "plan" in payload and payload["plan"]["decision"] == "fail-closed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
