#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Command line access to the local test timing ledger and run status files."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from lib import test_timing_store as store


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _run_status_path(run_id: str, repo: str | None) -> Path:
    root = Path(repo).resolve() if repo else Path.cwd().resolve()
    return root / ".cache" / "test_runs" / f"{run_id}.json"


def cmd_estimate(args: argparse.Namespace) -> int:
    payload = store.estimate(
        args.command_key,
        db_path=args.db,
        selector=args.selector,
        suite=args.suite,
        tier=args.tier,
        host=args.host,
        runtime_version=args.runtime_version,
        xcode_or_device=args.xcode_or_device,
        dataset=args.dataset,
        resource_class=args.resource_class,
        cache_status=args.cache_status,
        resource_wait_estimate_s=args.resource_wait_estimate_s,
    )
    _emit(payload, args.json)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = _run_status_path(args.run_id, args.repo)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        payload = {
            "schema": "kg.test.bundle.v1",
            "run_id": args.run_id,
            "status": "not_found",
            "error": f"{type(exc).__name__}: {exc}",
        }
    _emit(payload, args.json)
    return 0 if payload.get("status") != "not_found" else 1


def cmd_wait(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout_s
    while True:
        path = _run_status_path(args.run_id, args.repo)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"run_id": args.run_id, "status": "pending"}
        status = payload.get("status")
        if status in {"passed", "failed", "cancelled", "error", "timeout"}:
            _emit(payload, args.json)
            return 0 if status == "passed" else 1
        if time.monotonic() >= deadline:
            payload = {**payload, "run_id": args.run_id, "status": "timeout"}
            _emit(payload, args.json)
            return 1
        time.sleep(args.interval_s)


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit one JSON object")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    estimate = sub.add_parser("estimate")
    estimate.add_argument("--command-key", required=True)
    for name in ("selector", "suite", "tier", "host", "runtime-version",
                 "xcode-or-device", "dataset", "resource-class", "cache-status"):
        estimate.add_argument(f"--{name}", dest=name.replace("-", "_"))
    estimate.add_argument("--resource-wait-estimate-s", type=float, default=0.0)
    estimate.add_argument("--db")
    _add_json(estimate)
    estimate.set_defaults(func=cmd_estimate)

    for verb, func in (("status", cmd_status), ("wait", cmd_wait)):
        command = sub.add_parser(verb)
        command.add_argument("--run-id", required=True)
        command.add_argument("--repo")
        if verb == "wait":
            command.add_argument("--interval-s", type=float, default=1.0)
            command.add_argument("--timeout-s", type=float, default=3600.0)
        _add_json(command)
        command.set_defaults(func=func)
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    raise SystemExit(parsed.func(parsed))
