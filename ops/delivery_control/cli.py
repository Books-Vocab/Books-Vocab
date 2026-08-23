"""Thin command surface for the deterministic delivery services."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from .adapters.operation_lock import OperationLock
from .adapters.runtime import RuntimeStatusMap
from .application import DeliveryApplication, build_application
from .domain.candidate_issues import CandidateSpec
from .domain.errors import DeliveryContractError, DeliverySourceError
from .domain.runtime_models import RuntimeReceipt, RuntimeState
from .domain.states import HoldKind
from .services.candidate_contract import parse_candidate_body, render_candidate_body
from .services.pr_contract import validate_pull_request_body

COMMAND_SCHEMA = "kg.delivery.command.v1"
MUTATING_COMMANDS = frozenset(
    {
        "admit-candidate",
        "watchdog-claim",
        "runtime-receipt",
        "receipt",
        "publish",
        "record-published-base",
        "release-published",
        "queue",
        "reconcile-holds",
        "repair-pr-metadata",
        "trigger-required",
        "cleanup-merged",
        "abandon-pr",
        "cleanup-abandoned",
        "discard-abandoned-handback",
        "discard-orphan-branch",
        "discard-unregistered-branch",
        "sync-main",
    }
)


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

    inspect = commands.add_parser("inspect", help="classify every known delivery lane")
    inspect.add_argument(
        "--supervision-worktree",
        action="append",
        type=Path,
        default=[],
        help="exact supervision checkout path; repeat once per checkout",
    )
    commands.add_parser(
        "issue-inventory", help="inventory every open GitHub Issue without mutation"
    )
    commands.add_parser(
        "triage-plan", help="derive a deterministic raw Issue triage plan"
    )
    branch_audit = commands.add_parser(
        "branch-audit",
        help="audit every local/remote branch against registry, PR, and worktree facts",
    )
    branch_audit.add_argument(
        "--supervision-worktree",
        action="append",
        type=Path,
        default=[],
        help="exact supervision checkout path; repeat once per checkout",
    )
    branch_inspect = commands.add_parser(
        "branch-inspect",
        help="inspect one local branch's unlanded content without mutation",
    )
    branch_inspect.add_argument("--branch", required=True)
    branch_inspect.add_argument("--expected-head-sha")
    unreachable_inspect = commands.add_parser(
        "unreachable-commit-inspect",
        help="inspect one unreachable commit object without mutation",
    )
    unreachable_inspect.add_argument("--commit", required=True)
    unreachable_inspect.add_argument("--max-paths", type=int, default=200)
    branch_review_plan = commands.add_parser(
        "branch-review-plan",
        help="page blocked local-orphan content for read-only review",
    )
    branch_review_plan.add_argument("--offset", type=int, default=0)
    branch_review_plan.add_argument("--limit", type=int, default=5)
    metrics = commands.add_parser("metrics", help="measure current queue reservoirs")
    metrics.add_argument(
        "--supervision-worktree",
        action="append",
        type=Path,
        default=[],
        help="exact supervision checkout path; repeat once per checkout",
    )
    plan = commands.add_parser("plan", help="derive the next capacity actions")
    plan.add_argument(
        "--supervision-worktree",
        action="append",
        type=Path,
        default=[],
        help="exact supervision checkout path; repeat once per checkout",
    )
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
    watchdog.add_argument("--stale-after-seconds", type=int, default=300)
    watchdog_claim = commands.add_parser(
        "watchdog-claim",
        help="atomically claim one stale wake before external scheduler dispatch",
    )
    watchdog_claim.add_argument("--supervisor-thread", required=True)
    watchdog_claim.add_argument("--stale-after-seconds", type=int, default=300)

    runtime_receipt = commands.add_parser(
        "runtime-receipt",
        help="atomically publish one caller-owned runtime liveness receipt",
    )
    runtime_receipt.add_argument("--thread-id", required=True)
    runtime_receipt.add_argument(
        "--state", required=True, choices=tuple(item.value for item in RuntimeState)
    )
    runtime_receipt.add_argument("--cycle-id", required=True)
    runtime_receipt.add_argument("--last-action-id")
    runtime_receipt.add_argument("--clear-last-action", action="store_true")
    runtime_receipt.add_argument("--expected-cycle-id")
    runtime_receipt.add_argument("--lease-seconds", type=int)
    runtime_receipt.add_argument("--lease-until")
    runtime_receipt.add_argument("--expected-next-event-at")
    runtime_receipt.add_argument("--last-progress-at")
    runtime_receipt.add_argument("--observed-at")

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

    admit_candidate = commands.add_parser(
        "admit-candidate",
        help="admit exactly one triaged Issue as a typed candidate",
    )
    admit_candidate.add_argument("--issue", type=int, required=True)
    admit_candidate.add_argument("--expected-updated-at", required=True)
    admit_candidate.add_argument("--expected-body-sha256", required=True)
    admit_candidate.add_argument("--payload-file", type=Path, default=Path("-"))
    admit_candidate.add_argument("--triage-reason", required=True)
    admit_candidate.add_argument("--operator", required=True)

    receipt = commands.add_parser("receipt", help="normalize one active handback")
    receipt.add_argument("--lane", required=True)

    publish = commands.add_parser("publish", help="publish and release one handback")
    publish.add_argument("--lane", required=True)
    publish.add_argument("--title", required=True)

    published_base = commands.add_parser(
        "record-published-base",
        help="persist the exact GitHub PR base for one durable published lane",
    )
    published_base.add_argument("--pr", type=int, required=True)

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
    cleanup_abandoned = commands.add_parser(
        "cleanup-abandoned",
        help="remove exact abandoned branch residue with no PR history",
    )
    cleanup_abandoned.add_argument("--branch", required=True)
    discard_handback = commands.add_parser(
        "discard-abandoned-handback",
        help="discard one exact ownerless abandoned handback after CAS preflight",
    )
    discard_handback.add_argument("--branch", required=True)
    discard_handback.add_argument("--expected-head-sha", required=True)
    discard_handback.add_argument("--operator", required=True)
    discard_handback.add_argument("--reason", required=True)
    discard_orphan = commands.add_parser(
        "discard-orphan-branch",
        help="discard one unregistered local branch already contained in main",
    )
    discard_orphan.add_argument("--branch", required=True)
    discard_orphan.add_argument("--expected-head-sha", required=True)
    discard_orphan.add_argument("--operator", required=True)
    discard_orphan.add_argument("--reason", required=True)
    discard_unregistered = commands.add_parser(
        "discard-unregistered-branch",
        help="discard one explicitly reviewed unlanded local-only branch",
    )
    discard_unregistered.add_argument("--branch", required=True)
    discard_unregistered.add_argument("--expected-head-sha", required=True)
    discard_unregistered.add_argument("--expected-content-fingerprint", required=True)
    discard_unregistered.add_argument("--operator", required=True)
    discard_unregistered.add_argument("--reason", required=True)
    discard_unregistered.add_argument(
        "--confirm-unmerged",
        action="store_true",
        help="confirm that unlanded local commits may be discarded",
    )
    commands.add_parser("sync-main", help="ff-only synchronize canonical main")
    return parser


def run_command(args: argparse.Namespace, application: DeliveryApplication) -> object:
    if args.command == "inspect":
        return application.inspect(
            supervision_worktree_paths=tuple(args.supervision_worktree)
        )
    if args.command == "issue-inventory":
        inventory = application.issue_inventory()
        return {
            "schema": "kg.delivery.issue-inventory.v1",
            "raw_total": inventory.raw_open_issues,
            "partition_totals": inventory.disposition_counts,
            "unadmitted_open_issues": inventory.unadmitted_open_issues,
            "backlog_drained": inventory.backlog_drained,
            "complete": inventory.complete,
            "source_problems": inventory.problems,
            "source_entries": inventory.source_entries,
            "issues": inventory.records,
        }
    if args.command == "triage-plan":
        return {
            "schema": "kg.delivery.triage-plan.v1",
            "items": application.triage_plan(),
            "source_entries": application.issue_inventory().source_entries,
        }
    if args.command == "branch-audit":
        return application.branch_audit(
            supervision_worktree_paths=tuple(args.supervision_worktree)
        )
    if args.command == "branch-inspect":
        return application.branch_inspect(
            branch=args.branch,
            expected_head_sha=args.expected_head_sha,
        )
    if args.command == "unreachable-commit-inspect":
        return application.unreachable_commit_inspect(
            commit_sha=args.commit,
            max_paths=args.max_paths,
        )
    if args.command == "branch-review-plan":
        return application.branch_review_plan(offset=args.offset, limit=args.limit)
    if args.command == "metrics":
        return application.metrics(
            supervision_worktree_paths=tuple(args.supervision_worktree)
        )
    if args.command == "plan":
        return application.plan(
            supervision_worktree_paths=tuple(args.supervision_worktree)
        )
    if args.command == "dogfood-preflight":
        return application.dogfood_preflight(
            supervision_worktree_paths=tuple(args.supervision_worktree)
        )
    if args.command == "watchdog":
        return application.watchdog(
            supervisor_thread_id=args.supervisor_thread,
            stale_after_seconds=args.stale_after_seconds,
        )
    if args.command == "watchdog-claim":
        return application.watchdog_claim(
            supervisor_thread_id=args.supervisor_thread,
            stale_after_seconds=args.stale_after_seconds,
        )
    if args.command == "runtime-receipt":
        if args.clear_last_action and args.last_action_id is not None:
            raise DeliveryContractError(
                "runtime receipt cannot both clear and set last_action_id"
            )
        observed_at = _runtime_timestamp(args.observed_at, "observed_at")
        if observed_at is None:
            observed_at = datetime.now(UTC)
        last_progress_at = (
            _runtime_timestamp(args.last_progress_at, "last_progress_at") or observed_at
        )
        lease_until = _runtime_timestamp(args.lease_until, "lease_until")
        if args.lease_seconds is not None:
            if args.lease_seconds <= 0:
                raise DeliveryContractError("lease_seconds must be positive")
            if lease_until is not None:
                raise DeliveryContractError(
                    "runtime receipt cannot set lease_until and lease_seconds"
                )
            lease_until = observed_at + timedelta(seconds=args.lease_seconds)
        expected_next_event_at = _runtime_timestamp(
            args.expected_next_event_at, "expected_next_event_at"
        )
        last_action_id = args.last_action_id
        if last_action_id is None and not args.clear_last_action:
            current = application.runtime.runtime_receipt(args.thread_id)
            last_action_id = current.last_action_id if current is not None else None
        receipt = RuntimeReceipt(
            thread_id=args.thread_id,
            state=RuntimeState(args.state),
            last_progress_at=last_progress_at,
            observed_at=observed_at,
            lease_until=lease_until,
            expected_next_event_at=expected_next_event_at,
            cycle_id=args.cycle_id,
            last_action_id=last_action_id,
        )
        return application.write_runtime_receipt(
            receipt=receipt,
            expected_cycle_id=args.expected_cycle_id,
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
    if args.command == "admit-candidate":
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
        except (TypeError, ValueError) as error:
            raise DeliveryContractError(str(error)) from error
        expected_updated_at = _runtime_timestamp(
            args.expected_updated_at, "expected_updated_at"
        )
        if expected_updated_at is None:
            raise DeliveryContractError("expected_updated_at is required")
        return application.admit_candidate(
            issue_number=args.issue,
            expected_updated_at=expected_updated_at,
            expected_body_sha256=args.expected_body_sha256,
            spec=spec,
            triage_reason=args.triage_reason,
            operator=args.operator,
        )
    if args.command == "receipt":
        return application.receipt(args.lane)
    if args.command == "publish":
        return application.publish(lane_id=args.lane, title=args.title)
    if args.command == "record-published-base":
        return application.record_published_base(args.pr)
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
    if args.command == "cleanup-abandoned":
        return application.cleanup_abandoned(args.branch)
    if args.command == "discard-abandoned-handback":
        return application.discard_abandoned_handback(
            branch=args.branch,
            expected_head_sha=args.expected_head_sha,
            operator=args.operator,
            reason=args.reason,
        )
    if args.command == "discard-orphan-branch":
        return application.discard_orphan_branch(
            branch=args.branch,
            expected_head_sha=args.expected_head_sha,
            operator=args.operator,
            reason=args.reason,
        )
    if args.command == "discard-unregistered-branch":
        return application.discard_unregistered_branch(
            branch=args.branch,
            expected_head_sha=args.expected_head_sha,
            expected_content_fingerprint=args.expected_content_fingerprint,
            operator=args.operator,
            reason=args.reason,
            confirm_unmerged=args.confirm_unmerged,
        )
    if args.command == "sync-main":
        return application.sync_main()
    raise AssertionError(f"unhandled command: {args.command}")


def _runtime_timestamp(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise DeliveryContractError(f"{name} must be ISO-8601") from error
    if parsed.utcoffset() is None:
        raise DeliveryContractError(f"{name} must include a timezone")
    return parsed


def _result_exit_code(command: str, result: object) -> int:
    if command in {
        "branch-audit",
        "branch-review-plan",
        "unreachable-commit-inspect",
    }:
        complete = (
            result.get("complete")
            if isinstance(result, Mapping)
            else getattr(result, "complete", None)
        )
        return 0 if complete is True else 2
    if command != "dogfood-preflight":
        return 0
    ready = (
        result.get("ready")
        if isinstance(result, Mapping)
        else getattr(result, "ready", None)
    )
    return 0 if ready is True else 2


def _run_command_serialized(
    args: argparse.Namespace, application: DeliveryApplication
) -> object:
    if args.command not in MUTATING_COMMANDS:
        return run_command(args, application)
    repo = getattr(application, "repo", None)
    if repo is None:
        # Lightweight application fakes used by unit tests do not own a
        # repository.  Real applications always expose the canonical path.
        return run_command(args, application)
    with OperationLock(Path(repo), command=args.command):
        return run_command(args, application)


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
        result = _run_command_serialized(args, application)
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
                "verdict": _command_verdict(args.command, result),
                "result": _jsonable(result),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return _result_exit_code(args.command, result)


def _command_verdict(command: str, result: object) -> str:
    """Expose domain incompleteness separately from command transport success."""

    if command in {
        "branch-audit",
        "branch-review-plan",
        "unreachable-commit-inspect",
    }:
        complete = (
            result.get("complete")
            if isinstance(result, Mapping)
            else getattr(result, "complete", None)
        )
        return "complete" if complete is True else "incomplete"
    if command == "dogfood-preflight":
        ready = (
            result.get("ready")
            if isinstance(result, Mapping)
            else getattr(result, "ready", None)
        )
        return "ready" if ready is True else "blocked"
    return "success"


__all__ = [
    "COMMAND_SCHEMA",
    "DeliveryApplication",
    "RuntimeStatusMap",
    "build_application",
    "main",
    "run_command",
]
