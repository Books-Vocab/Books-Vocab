"""Argparse and rendering boundary for the reanchor transaction."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import worktree_registry as registry

from .domain import EXIT_BLOCK, EXIT_OK, SCHEMA
from .errors import ReanchorRefused
from .transaction import perform_reanchor


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("status") == "ready-for-owner-tests":
        print(
            f"✓ reanchored PR #{payload['merge_front_pr']} for owner tests at "
            f"{payload['worktree']}"
        )
    else:
        print(f"✗ reanchor refused: {payload.get('reason', 'unknown reason')}")


def cmd_reanchor(args: argparse.Namespace, *, freeze_reason: str | None = None) -> int:
    if freeze_reason:
        payload = {
            "schema": SCHEMA,
            "action": "reanchor",
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
        payload = perform_reanchor(
            repo=Path(args.repo).expanduser().resolve(),
            state_path=state_path,
            merge_front_pr=args.merge_front_pr,
            lane_id=args.lane,
            branch=args.branch,
            owner_thread_id=args.owner_thread_id,
            claim_generation=args.claim_generation,
            expected_remote_head=args.expected_remote_head,
            live_main=args.live_main,
            target=Path(args.path).expanduser().resolve(),
            preserve_conflict=args.preserve_conflict,
        )
    except ReanchorRefused as exc:
        payload = {
            "schema": SCHEMA,
            "action": "reanchor",
            "status": "blocked",
            "reason": exc.reason,
            **exc.details,
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    except (OSError, TypeError, ValueError) as exc:
        payload = {
            "schema": SCHEMA,
            "action": "reanchor",
            "status": "blocked",
            "reason": f"reanchor source error: {type(exc).__name__}: {exc}",
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    _emit(payload, as_json=args.json)
    return EXIT_BLOCK if payload.get("status") == "owner-action-required" else EXIT_OK


def add_parser(
    subparsers: Any,
    *,
    common: Callable[[argparse.ArgumentParser], None],
    handler: Callable[[argparse.Namespace], int],
    default_repo: Path,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "reanchor", help="recreate one machine-verified merge-front PR for its owner"
    )
    common(parser)
    parser.add_argument("--repo", default=str(default_repo))
    parser.add_argument("--merge-front-pr", type=int, required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--owner-thread-id", required=True)
    parser.add_argument("--claim-generation", type=int, required=True)
    parser.add_argument("--expected-remote-head", required=True)
    parser.add_argument("--live-main", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument(
        "--preserve-conflict",
        action="store_true",
        help="keep an exact rebase conflict registered for the original owner",
    )
    parser.set_defaults(func=handler)
    return parser
