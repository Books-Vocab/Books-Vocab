#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Standalone machine-readable adapter for the Gate-cost route matrix.

This adapter intentionally reports contract readiness separately from whether a
central runner consumes it.  Until Manager wiring lands, the honest result is
``contract_ready=true`` and ``runner_connected=false``.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import gate_cost_route_matrix as matrix

ADAPTER_SCHEMA = "kg.gate.cost.route-adapter.v1"
INTEGRATION_SCHEMA = "kg.gate.cost.route-integration.v1"
VERSION = 1
WIRING_NEXT_STEP = (
    "connect adapter through the existing planner and Manager gate after this ticket lands"
)


def _verified_runner_connection(evidence: Mapping[str, Any] | None) -> bool:
    """Accept connected status only from explicit, typed central-runner evidence."""
    if not isinstance(evidence, Mapping):
        return False
    return (
        evidence.get("schema") == "kg.gate.runner-connection.v1"
        and evidence.get("runner") == "ops/test_ops.sh"
        and evidence.get("connected") is True
        and evidence.get("verified") is True
        and evidence.get("source") == "central-runner"
    )


def _wiring_follow_up(runner_connected: bool) -> dict[str, Any] | None:
    if runner_connected:
        return None
    return {
        "owner": "manager",
        "next_step": WIRING_NEXT_STEP,
        "files": ["ops/test_ops.sh"],
    }


def build_adapter_output(
    *,
    changed_files: Iterable[str] | None = None,
    fingerprint: Mapping[str, Any] | None = None,
    requested_tier: str | None = None,
    runner_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable adapter payload without touching an execution runner."""
    routing = matrix.route(
        changed_files=changed_files,
        fingerprint=fingerprint,
        requested_tier=requested_tier,
    )
    runner_connected = _verified_runner_connection(runner_evidence)
    follow_up = _wiring_follow_up(runner_connected)
    planner_input = {
        "changed_files": routing["changed_files"],
        "gate_tier": routing["selected_tier"],
        "route_id": routing["route_id"],
        "fallback": routing["fallback"],
    }
    integration = {
        "schema": INTEGRATION_SCHEMA,
        "version": VERSION,
        "contract_ready": True,
        "runner_connected": runner_connected,
        "source": "standalone-adapter" if not runner_connected else "central-runner",
        "wiring_follow_up": follow_up,
    }
    return {
        "schema": ADAPTER_SCHEMA,
        "version": VERSION,
        "contract_ready": True,
        "runner_connected": runner_connected,
        "wiring_follow_up": follow_up,
        "routing": routing,
        "planner_input": planner_input,
        "integration": integration,
    }


def dumps_adapter_output(**kwargs: Any) -> str:
    """Serialize the adapter contract deterministically for CLI/receipt use."""
    return json.dumps(
        build_adapter_output(**kwargs),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def _load_object(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON object required: {path}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--fingerprint-file")
    parser.add_argument("--runner-evidence-file")
    parser.add_argument("--requested-tier")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        payload = build_adapter_output(
            changed_files=args.changed_file,
            fingerprint=_load_object(args.fingerprint_file),
            requested_tier=args.requested_tier,
            runner_evidence=_load_object(args.runner_evidence_file),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"schema": ADAPTER_SCHEMA, "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 64
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
