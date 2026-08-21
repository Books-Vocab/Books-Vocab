"""Atomic claim, Scope, and owner mutations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lib.worktree_scope import coerce_scope, normalise_scope

from .admission import ownership_conflicts
from .constants import EXIT_CLAIMED, EXIT_OK, EXIT_USAGE
from .environment import load_state, repo_root, resolve_now, state_path
from .handback import advance_claim
from .records import (
    SCHEMA,
    STATUS_ACTIVE,
    STATUS_CLEANUP_PENDING,
    active_records,
    external_ids,
    legacy_external_ids,
    norm_path,
    record_matches,
)
from .storage import ledger_lock, save_state


def scope_from_args(args: argparse.Namespace, *, required: bool = False) -> object:
    raw = getattr(args, "scope", None)
    scope_file = getattr(args, "scope_file", None)
    if raw is not None and scope_file is not None:
        raise ValueError("--scope and --scope-file are mutually exclusive")
    if scope_file is not None:
        raw = Path(scope_file).expanduser().read_text(encoding="utf-8")
    if raw is None:
        if required:
            raise ValueError("a structured Scope is required")
        return None
    return coerce_scope(raw)


def claim_generation(record: dict[str, Any], field: str) -> int | None:
    value = record.get(field, 0)
    return value if type(value) is int and value >= 0 else None


def register_record(
    state: dict[str, Any],
    *,
    branch: str,
    path: str,
    intent: str,
    base: str,
    external_ids_value: list[str],
    scope: object = None,
    codex_thread_id: str | None = None,
    delegated: bool | None = None,
    at: str | None = None,
) -> tuple[int, dict[str, Any]]:
    branch = branch.strip()
    path = norm_path(path)
    if not branch or not intent.strip():
        return EXIT_USAGE, {"reason": "branch and intent are required"}
    try:
        ids = external_ids(external_ids_value)
    except (TypeError, ValueError) as exc:
        return EXIT_USAGE, {"reason": str(exc)}
    if scope is not None:
        try:
            scope = normalise_scope(scope)
        except ValueError as exc:
            return EXIT_USAGE, {"reason": str(exc)}
    owners = ownership_conflicts(
        state,
        branch=branch,
        path=path,
        external_ids=ids,
        scope=scope,
    )
    if owners:
        return EXIT_CLAIMED, {
            "reason": "external reference or Scope is already owned",
            "owners": owners,
        }
    _, now_iso = resolve_now(at)
    matching_records = [
        record
        for record in state["records"]
        if isinstance(record, dict)
        and (
            record.get("branch") == branch
            or norm_path(str(record.get("path") or "")) == path
        )
    ]
    cleanup_leases = [
        record
        for record in matching_records
        if record.get("status") == STATUS_CLEANUP_PENDING
    ]
    if cleanup_leases:
        existing = cleanup_leases[0]
        return EXIT_CLAIMED, {
            "reason": "local assets are protected by an exact cleanup lease",
            "branch": existing.get("branch"),
            "path": existing.get("path"),
            "claim_generation": existing.get("claim_generation"),
        }
    live_records = [
        record for record in matching_records if record.get("status") == STATUS_ACTIVE
    ]
    existing = live_records[0] if live_records else None
    generations = [
        generation
        for record in matching_records
        if (generation := claim_generation(record, "claim_generation")) is not None
    ]
    next_generation = max(generations, default=-1) + 1
    if existing is not None:
        existing["claim_generation"] = next_generation
        existing.update(
            {
                "branch": branch,
                "path": path,
                "intent": intent.strip(),
                "base": base,
                "external_ids": ids,
                "claimed_at": existing.get("claimed_at") or now_iso,
            }
        )
        if scope is not None:
            existing["scope"] = scope
        if codex_thread_id is not None:
            existing["codex_thread_id"] = codex_thread_id
        if delegated is not None:
            existing["delegated"] = delegated
        return EXIT_OK, existing
    record: dict[str, Any] = {
        "branch": branch,
        "path": path,
        "intent": intent.strip(),
        "base": base,
        "status": STATUS_ACTIVE,
        "external_ids": ids,
        "scope": scope,
        "codex_thread_id": codex_thread_id,
        "delegated": delegated,
        "created_at": now_iso,
        "claimed_at": now_iso,
        "resolved_at": None,
        "claim_generation": next_generation,
        "handed_back_at": None,
        "handed_back_sha": None,
    }
    state["records"].append(record)
    return EXIT_OK, record


def cmd_register(args: argparse.Namespace) -> int:
    target = state_path(args)
    try:
        scope = scope_from_args(args)
        ids = external_ids(getattr(args, "external_id", None))
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {"schema": SCHEMA, "action": "refused", "reason": str(exc)},
                ensure_ascii=False,
            )
        )
        return EXIT_USAGE
    with ledger_lock(target):
        state = load_state(target)
        rc, record = register_record(
            state,
            branch=args.branch,
            path=args.path or str(repo_root()),
            intent=args.intent,
            base=args.base,
            external_ids_value=ids,
            scope=scope,
            codex_thread_id=args.codex_thread_id,
            delegated=args.delegated,
            at=args.at,
        )
        if rc == EXIT_OK:
            save_state(target, state)
    payload = {
        "schema": SCHEMA,
        "action": "register" if rc == EXIT_OK else "refused",
        "record": record,
    }
    print(
        json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json
        else (
            f"✓ registered [{record.get('branch')}]"
            if rc == EXIT_OK
            else f"✗ register refused: {record.get('reason')}"
        )
    )
    return rc


def cmd_scope_set(args: argparse.Namespace) -> int:
    target = state_path(args)
    try:
        scope = normalise_scope(scope_from_args(args, required=True))
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"schema": SCHEMA, "action": "refused", "reason": str(exc)},
                ensure_ascii=False,
            )
        )
        return EXIT_USAGE
    with ledger_lock(target):
        state = load_state(target)
        matches = [
            record
            for record in active_records(state)
            if record_matches(record, branch=args.branch, path=args.path)
        ]
        if len(matches) != 1:
            reason = "scope selector must match exactly one active worktree"
            print(
                json.dumps(
                    {"schema": SCHEMA, "action": "refused", "reason": reason},
                    ensure_ascii=False,
                )
            )
            return EXIT_USAGE
        record = matches[0]
        if record.get("scope") != scope:
            owners = ownership_conflicts(
                state,
                branch=str(record.get("branch") or ""),
                path=str(record.get("path") or ""),
                external_ids=legacy_external_ids(record),
                scope=scope,
            )
            if owners:
                print(
                    json.dumps(
                        {
                            "schema": SCHEMA,
                            "action": "refused",
                            "reason": "Scope is already owned by another in-flight worktree",
                            "owners": owners,
                        },
                        ensure_ascii=False,
                    )
                )
                return EXIT_CLAIMED
            advance_claim(record)
            record["scope"] = scope
        save_state(target, state)
    print(
        json.dumps(
            {"schema": SCHEMA, "action": "scope-set", "record": matches[0]},
            indent=2,
            ensure_ascii=False,
        )
        if args.json
        else f"✓ scope set [{matches[0].get('branch')}]"
    )
    return EXIT_OK


def cmd_owner_bind(args: argparse.Namespace) -> int:
    target = state_path(args)
    with ledger_lock(target):
        state = load_state(target)
        matches = [
            record
            for record in active_records(state)
            if record_matches(record, branch=args.branch, path=args.path)
        ]
        if len(matches) != 1:
            print(
                "✗ owner selector must match exactly one active worktree",
                file=sys.stderr,
            )
            return EXIT_USAGE
        record = matches[0]
        assignment_changed = record.get("codex_thread_id") != args.codex_thread_id
        if args.delegated is not None:
            assignment_changed = (
                assignment_changed or record.get("delegated") != args.delegated
            )
        if assignment_changed:
            advance_claim(record)
        record["codex_thread_id"] = args.codex_thread_id
        if args.delegated is not None:
            record["delegated"] = args.delegated
        save_state(target, state)
    print(
        json.dumps(
            {"schema": SCHEMA, "action": "owner-bind", "record": matches[0]},
            indent=2,
            ensure_ascii=False,
        )
        if args.json
        else f"✓ owner bound [{matches[0].get('branch')}]"
    )
    return EXIT_OK
