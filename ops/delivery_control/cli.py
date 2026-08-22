"""Thin command surface for the deterministic delivery services."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .adapters.runtime import RuntimeStatusMap
from .application import DeliveryApplication, build_application
from .domain.candidate_issues import CandidateSpec
from .domain.errors import DeliveryContractError, DeliverySourceError
from .domain.states import HoldKind
from .services.candidate_contract import parse_candidate_body, render_candidate_body
from .services.pr_contract import validate_pull_request_body

COMMAND_SCHEMA = "kg.delivery.command.v1"


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic KG delivery control plane"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--runtime-status-file", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("inspect", help="classify every known delivery lane")
    commands.add_parser("metrics", help="measure current queue reservoirs")
    commands.add_parser("plan", help="derive the next capacity actions")
    dogfood = commands.add_parser(
        "dogfood-preflight", help="verify the four-role canary launch baseline"
    )
    dogfood.add_argument(
        "--supervision-worktree",
        action="append",
        type=Path,
        default=[],
        help="exact supervision checkout path; repeat once per checkout",
    )
    watchdog = commands.add_parser(
        "watchdog", help="read liveness and return a non-dispatching wake decision"
    )
    watchdog.add_argument("--supervisor-thread", required=True)
    watchdog.add_argument("--stale-after-seconds", type=int, default=600)

    validate = commands.add_parser(
        "validate-pr-body", help="validate one durable PR receipt"
    )
    validate.add_argument("--head-sha", required=True)
    validate.add_argument("--body-file", type=Path, default=Path("-"))

    render_candidate = commands.add_parser(
        "render-candidate-body",
        help="render one canonical dispatchable candidate Issue body",
    )
    render_candidate.add_argument("--payload-file", type=Path, default=Path("-"))

    validate_candidate = commands.add_parser(
        "validate-candidate-body",
        help="validate one dispatchable candidate Issue body",
    )
    validate_candidate.add_argument("--body-file", type=Path, default=Path("-"))

    receipt = commands.add_parser("receipt", help="normalize one active handback")
    receipt.add_argument("--lane", required=True)

    publish = commands.add_parser("publish", help="publish and release one handback")
    publish.add_argument("--lane", required=True)
    publish.add_argument("--title", required=True)

    release = commands.add_parser(
        "release-published", help="retry local release after durable PR publication"
    )
    release.add_argument("--pr", type=int, required=True)

    queue = commands.add_parser("queue", help="admit one exact PR to merge queue")
    queue.add_argument("--pr", type=int, required=True)
    queue.add_argument(
        "--hold", action="append", choices=tuple(item.value for item in HoldKind)
    )

    reconcile_holds = commands.add_parser(
        "reconcile-holds", help="rewrite typed PR holds after explicit clearance"
    )
    reconcile_holds.add_argument("--pr", type=int, required=True)
    hold_choice = reconcile_holds.add_mutually_exclusive_group(required=True)
    hold_choice.add_argument(
        "--hold", action="append", choices=tuple(item.value for item in HoldKind)
    )
    hold_choice.add_argument("--clear-all", action="store_true")

    repair_metadata = commands.add_parser(
        "repair-pr-metadata",
        help="restore canonical body metadata on one durable PR",
    )
    repair_metadata.add_argument("--pr", type=int, required=True)

    commands.add_parser(
        "trigger-required", help="dispatch required checks for one exact published PR"
    ).add_argument("--pr", type=int, required=True)

    cleanup = commands.add_parser(
        "cleanup-merged", help="remove exact merged branch residue"
    )
    cleanup.add_argument("--pr", type=int, required=True)
    abandon = commands.add_parser(
        "abandon-pr",
        help="close and terminalize one exact post-publication PR",
    )
    abandon.add_argument("--pr", type=int, required=True)
    commands.add_parser("sync-main", help="ff-only synchronize canonical main")
    return parser


def run_command(args: argparse.Namespace, application: DeliveryApplication) -> object:
    if args.command == "inspect":
        return application.inspect()
    if args.command == "metrics":
        return application.metrics()
    if args.command == "plan":
        return application.plan()
    if args.command == "dogfood-preflight":
        return application.dogfood_preflight(
            supervision_worktree_paths=tuple(args.supervision_worktree)
        )
    if args.command == "watchdog":
        return application.watchdog(
            supervisor_thread_id=args.supervisor_thread,
            stale_after_seconds=args.stale_after_seconds,
        )
    if args.command == "validate-pr-body":
        body = (
            sys.stdin.read()
            if args.body_file == Path("-")
            else args.body_file.read_text(encoding="utf-8")
        )
        return validate_pull_request_body(body, expected_head_sha=args.head_sha)
    if args.command == "render-candidate-body":
        raw = (
            sys.stdin.read()
            if args.payload_file == Path("-")
            else args.payload_file.read_text(encoding="utf-8")
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DeliveryContractError("candidate payload is invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise DeliveryContractError("candidate payload must be an object")
        try:
            spec = CandidateSpec.from_payload(payload)
        except ValueError as error:
            raise DeliveryContractError(str(error)) from error
        return {"body": render_candidate_body(spec), "contract": spec}
    if args.command == "validate-candidate-body":
        body = (
            sys.stdin.read()
            if args.body_file == Path("-")
            else args.body_file.read_text(encoding="utf-8")
        )
        return parse_candidate_body(body)
    if args.command == "receipt":
        return application.receipt(args.lane)
    if args.command == "publish":
        return application.publish(lane_id=args.lane, title=args.title)
    if args.command == "release-published":
        return application.release_published(args.pr)
    if args.command == "queue":
        return application.enqueue(
            pull_request_number=args.pr,
            holds=frozenset(HoldKind(item) for item in args.hold or ()),
        )
    if args.command == "reconcile-holds":
        return application.reconcile_holds(
            pull_request_number=args.pr,
            holds=frozenset(HoldKind(item) for item in args.hold or ()),
            clear_all=args.clear_all,
        )
    if args.command == "repair-pr-metadata":
        return application.repair_metadata(args.pr)
    if args.command == "trigger-required":
        return application.trigger_required(args.pr)
    if args.command == "cleanup-merged":
        return application.cleanup_merged(args.pr)
    if args.command == "abandon-pr":
        return application.abandon_pr(args.pr)
    if args.command == "sync-main":
        return application.sync_main()
    raise AssertionError(f"unhandled command: {args.command}")


def _result_exit_code(command: str, result: object) -> int:
    if command != "dogfood-preflight":
        return 0
    ready = (
        result.get("ready")
        if isinstance(result, Mapping)
        else getattr(result, "ready", None)
    )
    return 0 if ready is True else 2


def main(
    argv: Sequence[str] | None = None,
    *,
    application_factory: Any = build_application,
) -> int:
    args = _parser().parse_args(argv)
    try:
        application = application_factory(
            repo=args.repo,
            runtime_status_file=args.runtime_status_file,
        )
        result = run_command(args, application)
    except (DeliveryContractError, DeliverySourceError, OSError) as error:
        print(
            json.dumps(
                {
                    "schema": COMMAND_SCHEMA,
                    "command": args.command,
                    "ok": False,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "schema": COMMAND_SCHEMA,
                "command": args.command,
                "ok": True,
                "result": _jsonable(result),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return _result_exit_code(args.command, result)


__all__ = [
    "COMMAND_SCHEMA",
    "DeliveryApplication",
    "RuntimeStatusMap",
    "build_application",
    "main",
    "run_command",
]
