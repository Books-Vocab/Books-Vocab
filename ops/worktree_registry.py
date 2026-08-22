#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Compatibility CLI for the machine-local worktree ownership ledger.

GitHub owns Issue and PR lifecycle. The implementation behind this stable
entrypoint is split by responsibility in ``worktree_registry_core``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from delivery_control.adapters.operation_lock import OperationLock
from lib.worktree_scope import normalise_scope
from worktree_registry_core.claims import (
    claim_generation as _claim_generation,
)
from worktree_registry_core.claims import (
    cmd_owner_bind,
    cmd_register,
    cmd_scope_set,
)
from worktree_registry_core.claims import register_record as _core_register_record
from worktree_registry_core.claims import scope_from_args as _scope_from_args
from worktree_registry_core.cli import build_parser
from worktree_registry_core.constants import (
    EXIT_CLAIMED,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_USAGE,
)
from worktree_registry_core.environment import (
    common_anchor,
    default_state_path,
    load_state,
    repo_root,
    resolve_now,
)
from worktree_registry_core.environment import git as _git
from worktree_registry_core.handback import seal_body as _seal_body
from worktree_registry_core.handback import seal_with_digest as _seal_with_digest
from worktree_registry_core.handback_cli import cmd_hand_back, validate_handback_seal
from worktree_registry_core.handback_cli import (
    has_valid_physical as _has_valid_handback,
)
from worktree_registry_core.handback_cli import (
    has_valid_stored as _has_valid_stored_handback,
)
from worktree_registry_core.inspection import cmd_list
from worktree_registry_core.inspection import record_view as _record_view
from worktree_registry_core.lifecycle import (
    PUBLIC_RESOLVE_STATUSES,
    TERMINAL_PROOF_SCHEMA,
    terminal_proof_with_digest,
)
from worktree_registry_core.lifecycle_cli import cmd_resolve as _cmd_resolve
from worktree_registry_core.maintenance import cmd_compact, cmd_sweep
from worktree_registry_core.published_base import cmd_record_published_base
from worktree_registry_core.records import (
    SCHEMA,
    STATUS_ACTIVE,
    STATUS_CLEANUP_PENDING,
)
from worktree_registry_core.records import active_records as _active_records
from worktree_registry_core.records import compact_record as _compact_record
from worktree_registry_core.records import (
    legacy_external_ids as _legacy_external_ids,
)
from worktree_registry_core.records import record_matches as _record_matches
from worktree_registry_core.storage import ledger_lock as _ledger_lock
from worktree_registry_core.storage import save_state

RESOLVE_STATUS = (*PUBLIC_RESOLVE_STATUSES, "merged")
REGISTRY_MUTATING_COMMANDS = frozenset(
    {
        "register",
        "scope-set",
        "owner-bind",
        "hand-back",
        "resolve",
        "record-published-base",
        "sweep",
        "compact",
    }
)


def _requires_operation_lock(args: argparse.Namespace) -> bool:
    if args.command in {"sweep", "compact"}:
        return bool(args.commit)
    return args.command in REGISTRY_MUTATING_COMMANDS

# Existing coordinators import these names directly. They remain a narrow
# compatibility surface while policy and command behavior live in core modules.
__all__ = (
    "EXIT_CLAIMED",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "EXIT_USAGE",
    "PUBLIC_RESOLVE_STATUSES",
    "SCHEMA",
    "STATUS_ACTIVE",
    "STATUS_CLEANUP_PENDING",
    "TERMINAL_PROOF_SCHEMA",
    "_active_records",
    "_claim_generation",
    "_compact_record",
    "_git",
    "_has_valid_handback",
    "_has_valid_stored_handback",
    "_ledger_lock",
    "_legacy_external_ids",
    "_record_matches",
    "_record_view",
    "_scope_from_args",
    "_seal_body",
    "_seal_with_digest",
    "common_anchor",
    "default_state_path",
    "load_state",
    "normalise_scope",
    "repo_root",
    "resolve_now",
    "save_state",
    "terminal_proof_with_digest",
    "validate_handback_seal",
)


def _register_record(
    state: dict[str, Any],
    *,
    branch: str,
    path: str,
    intent: str,
    base: str,
    external_ids: list[str],
    scope: object = None,
    codex_thread_id: str | None = None,
    delegated: bool | None = None,
    at: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Preserve the original Python call signature for local coordinators."""
    return _core_register_record(
        state,
        branch=branch,
        path=path,
        intent=intent,
        base=base,
        external_ids_value=external_ids,
        scope=scope,
        codex_thread_id=codex_thread_id,
        delegated=delegated,
        at=at,
    )


def cmd_resolve(args: argparse.Namespace) -> int:
    return _cmd_resolve(args, resolve_statuses=RESOLVE_STATUS)


def _parser() -> argparse.ArgumentParser:
    return build_parser(
        {
            "register": cmd_register,
            "scope-set": cmd_scope_set,
            "owner-bind": cmd_owner_bind,
            "list": cmd_list,
            "hand-back": cmd_hand_back,
            "resolve": cmd_resolve,
            "record-published-base": cmd_record_published_base,
            "sweep": cmd_sweep,
            "compact": cmd_compact,
        },
        resolve_statuses=RESOLVE_STATUS,
    )


def main(argv: list[str] | None = None, *, acquire_lock: bool = True) -> int:
    args = _parser().parse_args(argv)
    if acquire_lock and _requires_operation_lock(args):
        with OperationLock(common_anchor(), command=f"registry:{args.command}"):
            return int(args.func(args))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
