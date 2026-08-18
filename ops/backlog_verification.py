"""Verification command orchestration for the backlog CLI.

This module owns the two verification doors: full re-verification and the
read-only ``--static-only`` feedback command.  Store, validation, acceptance,
and serialization remain injected dependencies so the CLI façade keeps its
existing seams without importing the façade back into this module.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class VerificationDeps:
    """Callbacks needed by the verification command family."""

    load_entry: Callable[[Path, str], dict]
    closure_changes: Callable[..., dict]
    merged_and_validated: Callable[..., dict]
    gate_closure: Callable[[dict, dict, bool], dict | None]
    check_acceptance_cmd: Callable[[dict], list[dict]]
    run_static_acceptance: Callable[[str, str], dict]
    entry_path: Callable[[Path, str], Path]
    write_atomic: Callable[[Path, str], None]
    dumps: Callable[[dict], str]
    error_type: type[Exception] = ValueError
    entry_lock: Callable[..., Any] | None = None
    acceptance_lock: Callable[..., Any] | None = None
    static_command: Callable[[Any], int] | None = None


def _with_entry_lock(deps: VerificationDeps, store: Path, entry_id: str):
    if deps.entry_lock is None:
        raise RuntimeError("verification command requires an entry_lock dependency")
    return deps.entry_lock(deps.entry_path(store, entry_id))


def cmd_verify_static(args, *, deps: VerificationDeps) -> int:
    """Execute a ticket's optional fast feedback criterion, read-only."""
    if args.commit:
        raise deps.error_type("--static-only is read-only; drop --commit")
    forbidden = [
        flag
        for flag, value in (
            ("--verdict", args.verdict),
            ("--by", args.by),
            ("--evidence", args.evidence),
            ("--at", args.at),
            ("--status", args.status),
            ("--fixed-by", args.fixed_by),
            ("--fixed-elsewhere", args.fixed_elsewhere),
            ("--contract-status", args.contract_status),
            ("--contract-baseline", args.contract_baseline),
            ("--contract-checked-at", args.contract_checked_at),
            ("--contract-checked-by", args.contract_checked_by),
            ("--contract-evidence", args.contract_evidence),
        )
        if value not in (None, "", [])
    ]
    if forbidden:
        raise deps.error_type(
            "--static-only cannot be combined with mutation/verdict flags: "
            + ", ".join(forbidden)
        )

    entry = deps.load_entry(args.store, args.id)
    cmd = str(entry.get("acceptance_cmd_static") or "").strip()
    if not cmd:
        raise deps.error_type(
            f"{args.id} has no acceptance_cmd_static; this is optional worker "
            "feedback and does not replace the full acceptance_cmd"
        )
    problems = deps.check_acceptance_cmd(entry)
    static_problems = [
        problem
        for problem in problems
        if str(problem.get("kind", "")).startswith("acceptance-static-")
        or problem.get("kind") == "acceptance-static-without-cmd"
    ]
    if static_problems:
        raise deps.error_type(
            f"{args.id} acceptance_cmd_static is invalid: {static_problems}"
        )
    outcome = deps.run_static_acceptance(args.id, cmd)
    payload = {
        "schema": "kg.backlog.verify-static.v1",
        "mode": "read-only",
        "id": args.id,
        "acceptance": outcome,
        "closure_uses": "acceptance_cmd",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(
            f"[static-only] {args.id}: rc={outcome['rc']} "
            f"expected=0 {'OK' if outcome['ok'] else 'MISMATCH'}"
        )
    return 0 if outcome["ok"] else (124 if outcome["rc"] is None else 1)


def cmd_verify(
    args, *, deps: VerificationDeps, lock_held: bool = False,
    acceptance_only: bool = False, skip_acceptance: bool = False,
) -> int:
    """Record a full re-verification as one atomic lifecycle act."""
    if args.static_only:
        static_command = deps.static_command or (
            lambda static_args: cmd_verify_static(static_args, deps=deps)
        )
        return static_command(args)

    missing = [
        flag
        for flag, value in (
            ("--verdict", args.verdict),
            ("--by", args.by),
            ("--evidence", args.evidence),
        )
        if value is None
    ]
    if missing:
        print(
            "verify: the following arguments are required unless --static-only "
            f"is selected: {', '.join(missing)}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.commit and not lock_held:
        if args.status == "fixed" and deps.acceptance_lock is not None:
            with deps.acceptance_lock(deps.entry_path(args.store, args.id)):
                preflight_rc = cmd_verify(
                    args, deps=deps, lock_held=True, acceptance_only=True,
                )
            if preflight_rc != 0:
                return preflight_rc
            with _with_entry_lock(deps, args.store, args.id):
                return cmd_verify(
                    args, deps=deps, lock_held=True, skip_acceptance=True,
                )
        with _with_entry_lock(deps, args.store, args.id):
            return cmd_verify(args, deps=deps, lock_held=True)

    changes = deps.closure_changes(
        verdict=args.verdict,
        by=args.by,
        evidence=args.evidence,
        at=args.at,
        status=args.status,
        fixed_by=args.fixed_by,
        fixed_elsewhere=args.fixed_elsewhere,
        contract_status=args.contract_status,
        contract_baseline=args.contract_baseline,
        contract_checked_at=args.contract_checked_at,
        contract_checked_by=args.contract_checked_by,
        contract_evidence=args.contract_evidence,
    )
    current = deps.load_entry(args.store, args.id)
    merged = deps.merged_and_validated(current, changes, args.id)
    acceptance = (
        getattr(args, "_acceptance_result", None)
        if skip_acceptance
        else deps.gate_closure(current, changes, args.commit)
    )
    if acceptance_only:
        args._acceptance_result = acceptance
        return 0
    if not args.commit:
        if args.json:
            print(
                json.dumps(
                    {
                        "schema": "kg.backlog.verify.v1",
                        "mode": "dry-run",
                        "id": args.id,
                        "changes": changes,
                        **({"acceptance": acceptance} if acceptance else {}),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            for field, value in changes.items():
                print(
                    f"[dry-run] {args.id} {field}: "
                    f"{str(current.get(field))[:40]!r} -> {value!r}"
                )
            print("  (dry-run — pass --commit to land)")
        return 0

    deps.write_atomic(
        deps.entry_path(args.store, args.id), deps.dumps(merged)
    )
    if args.json:
        print(
            json.dumps(
                {
                    "schema": "kg.backlog.verify.v1",
                    "mode": "commit",
                    "id": args.id,
                    "changes": changes,
                    "entry": merged,
                    **({"acceptance": acceptance} if acceptance else {}),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(
            f"[commit] {args.id} verified {changes['verified_at']} "
            f"by {args.by}: {args.verdict}"
        )
    return 0
