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
import json
import os
import subprocess
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
from worktree_registry_core.environment import state_path as _state_path
from worktree_registry_core.handback import seal_body as _seal_body
from worktree_registry_core.handback import seal_with_digest as _seal_with_digest
from worktree_registry_core.handback_cli import (
    cmd_hand_back as _core_cmd_hand_back,
)
from worktree_registry_core.handback_cli import (
    has_valid_physical as _has_valid_handback,
)
from worktree_registry_core.handback_cli import (
    has_valid_stored as _has_valid_stored_handback,
)
from worktree_registry_core.handback_cli import (
    load_outcomes as _load_outcomes,
)
from worktree_registry_core.handback_cli import validate_handback_seal
from worktree_registry_core.inspection import cmd_list
from worktree_registry_core.inspection import record_view as _record_view
from worktree_registry_core.lifecycle import (
    DISCARD_PROOF_SCHEMA,
    PUBLIC_RESOLVE_STATUSES,
    TERMINAL_PROOF_SCHEMA,
    discard_proof_with_digest,
    superseded_proof_with_digest,
    terminal_proof_with_digest,
)
from worktree_registry_core.lifecycle_cli import (
    cmd_discard as _cmd_discard,
)
from worktree_registry_core.lifecycle_cli import (
    cmd_resolve as _cmd_resolve,
)
from worktree_registry_core.lifecycle_cli import (
    cmd_supersede as _cmd_supersede,
)
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
REVIEW_MANIFEST_FIELD = "review_manifest"
REVIEW_AUDIT_OK = 0
REVIEW_AUDIT_TIMEOUT_SECONDS = 30.0
REGISTRY_MUTATING_COMMANDS = frozenset(
    {
        "register",
        "scope-set",
        "owner-bind",
        "hand-back",
        "resolve",
        "discard",
        "supersede",
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
    "DISCARD_PROOF_SCHEMA",
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
    "discard_proof_with_digest",
    "load_state",
    "normalise_scope",
    "repo_root",
    "resolve_now",
    "save_state",
    "superseded_proof_with_digest",
    "terminal_proof_with_digest",
    "validate_handback_seal",
)


def _review_manifest_problems(
    value: object, *, worktree: Path, ticket_id: str
) -> tuple[list[dict[str, Any]], str | None]:
    """Validate and bind one repo-relative external-agent receipt.

    The connector owns external identity and liveness evidence.  The registry
    only checks that a hand-back references a manifest inside its worktree and
    that the dedicated structural auditor accepts it.  It never consults
    ``ops/task_registry.py`` or local process identity as external evidence.
    """
    if not isinstance(value, str) or not value.strip():
        return (
            [{"kind": "review-manifest-reference-invalid", "ticket_id": ticket_id}],
            None,
        )
    reference = value.strip()
    manifest = Path(reference)
    if manifest.is_absolute():
        return (
            [
                {
                    "kind": "review-manifest-reference-not-relative",
                    "ticket_id": ticket_id,
                }
            ],
            None,
        )
    try:
        resolved_worktree = worktree.resolve()
        resolved_manifest = (worktree / manifest).resolve()
        resolved_manifest.relative_to(resolved_worktree)
    except (OSError, ValueError):
        return (
            [
                {
                    "kind": "review-manifest-reference-outside-worktree",
                    "ticket_id": ticket_id,
                }
            ],
            None,
        )
    if not resolved_manifest.is_file():
        return (
            [
                {
                    "kind": "review-manifest-missing",
                    "ticket_id": ticket_id,
                    "path": reference,
                }
            ],
            None,
        )
    audit = worktree / "ops" / "review_audit.sh"
    if not audit.is_file() or not os.access(audit, os.X_OK):
        return (
            [
                {
                    "kind": "review-audit-missing-or-not-executable",
                    "ticket_id": ticket_id,
                }
            ],
            None,
        )
    try:
        proc = subprocess.run(
            [str(audit), "--manifest", str(resolved_manifest), "--json"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
            timeout=REVIEW_AUDIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return (
            [
                {
                    "kind": "review-manifest-audit-timeout",
                    "ticket_id": ticket_id,
                    "path": reference,
                    "timeout_seconds": REVIEW_AUDIT_TIMEOUT_SECONDS,
                }
            ],
            None,
        )
    except (OSError, UnicodeError) as exc:
        return (
            [
                {
                    "kind": "review-manifest-audit-unavailable",
                    "ticket_id": ticket_id,
                    "path": reference,
                    "detail": str(exc),
                }
            ],
            None,
        )
    if proc.returncode != REVIEW_AUDIT_OK:
        detail = (proc.stdout.strip() or proc.stderr.strip())[-1000:]
        return (
            [
                {
                    "kind": "review-manifest-audit-failed",
                    "ticket_id": ticket_id,
                    "path": reference,
                    "returncode": proc.returncode,
                    "detail": detail,
                }
            ],
            None,
        )
    return [], reference


def _handback_review_manifest_problems(
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    """Preflight optional review manifests before core hand-back mutation."""
    outcomes_path = getattr(args, "outcomes", None)
    if not outcomes_path:
        return []
    try:
        outcomes = _load_outcomes(Path(outcomes_path).expanduser())
        state = load_state(_state_path(args))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # The core command owns the canonical error and exit contract for
        # unreadable outcomes or registry state; do not shadow it here.
        return []
    matches = [
        record
        for record in _active_records(state)
        if _record_matches(record, branch=args.branch, path=args.path)
    ]
    if len(matches) != 1:
        return []
    worktree = Path(str(matches[0].get("path") or ""))
    problems: list[dict[str, Any]] = []
    for index, item in enumerate(outcomes):
        value = item.get(REVIEW_MANIFEST_FIELD)
        if value is None:
            continue
        ticket_id = str(item.get("ticket_id") or item.get("id") or f"outcome-{index}")
        manifest_problems, _ = _review_manifest_problems(
            value, worktree=worktree, ticket_id=ticket_id
        )
        problems.extend(manifest_problems)
    return problems


def cmd_hand_back(args: argparse.Namespace) -> int:
    problems = _handback_review_manifest_problems(args)
    if problems:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "action": "refused",
                        "reason": "external review manifest failed closed",
                        "problems": problems,
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print("✗ external review manifest failed closed", file=sys.stderr)
        return EXIT_PARTIAL
    return _core_cmd_hand_back(args)


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
            "discard": _cmd_discard,
            "supersede": _cmd_supersede,
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
