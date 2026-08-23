"""CLI boundary for exact same-owner published-claim resume."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import worktree_registry as registry

from .errors import ReanchorRefused
from .resume_domain import EXIT_BLOCK, EXIT_OK, SCHEMA
from .resume_transaction import perform_resume


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("status") == "ready-for-owner-fix":
        print(
            f"✓ resumed {payload['branch']} for its original owner at {payload['worktree']}"
        )
    else:
        print(f"✗ resume-published refused: {payload.get('reason', 'unknown reason')}")


def cmd_resume(args: argparse.Namespace, *, freeze_reason: str | None = None) -> int:
    if freeze_reason:
        payload = {
            "schema": SCHEMA,
            "action": "resume-published",
            "status": "blocked",
            "reason": freeze_reason,
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else registry.default_state_path()
    )
    try:
        payload = perform_resume(
            repo=Path(args.repo).expanduser().resolve(),
            state_path=state_path,
            lane_id=args.lane,
            branch=args.branch,
            owner_thread_id=args.owner_thread_id,
            claim_generation=args.claim_generation,
            expected_remote_head=args.expected_remote_head,
            target=Path(args.path).expanduser().resolve(),
            previous_handback=args.previous_handback,
            mode=args.mode,
        )
    except ReanchorRefused as exc:
        payload = {
            "schema": SCHEMA,
            "action": "resume-published",
            "status": "blocked",
            "reason": exc.reason,
            **exc.details,
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    except (OSError, TypeError, ValueError) as exc:
        payload = {
            "schema": SCHEMA,
            "action": "resume-published",
            "status": "blocked",
            "reason": f"resume-published source error: {type(exc).__name__}: {exc}",
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    _emit(payload, as_json=args.json)
    return EXIT_OK


def add_parser(
    subparsers: Any,
    *,
    common: Callable[[argparse.ArgumentParser], None],
    handler: Callable[[argparse.Namespace], int],
    default_repo: Path,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "resume-published",
        help="recreate one exact published claim for its original owner",
    )
    common(parser)
    parser.add_argument("--repo", default=str(default_repo))
    parser.add_argument("--lane", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--owner-thread-id", required=True)
    parser.add_argument("--claim-generation", type=int, required=True)
    parser.add_argument("--expected-remote-head", required=True)
    parser.add_argument(
        "--previous-handback",
        default=None,
        help="allow an owner-preserving refresh when the published PR advanced",
    )
    parser.add_argument(
        "--mode",
        choices=("required-failure", "maintenance"),
        default="required-failure",
        help=(
            "resume contract: required-failure needs an exact required failure; "
            "maintenance permits same-owner work on an exact published PR"
        ),
    )
    parser.add_argument("--path", required=True)
    parser.set_defaults(func=handler)
    return parser
