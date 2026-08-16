"""Mutation command orchestration for the backlog CLI.

The store, validation, acceptance gate, and CLI parser remain separate concerns.
This module owns only the command-level choreography for ``groom`` and
``update``.  Its dependencies are injected so the façade can preserve existing
monkeypatch seams while this module stays independent of ``backlog.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Callable


@dataclass(frozen=True)
class MutationDeps:
    """Callbacks and schema constants needed by mutation commands."""

    root: Path
    load_entry: Callable[[Path, str], dict]
    merged_and_validated: Callable[..., dict]
    gate_closure: Callable[[dict, dict, bool], dict | None]
    update_entry: Callable[..., dict]
    mutable_fields: tuple[str, ...]
    refused_update_fields: tuple[str, ...]
    digest_fields: tuple[str, ...]
    error_type: type[Exception] = ValueError
    entry_path: Callable[[Path, str], Path] | None = None
    entry_lock: Callable[..., Any] | None = None
    held_tickets: Callable[[], dict] | None = None
    main_commit: Callable[[], str | None] | None = None
    git: Callable[..., Any] | None = None
    today: Callable[[], str] | None = None
    report_pytest_selector_count: Callable[[str, str], None] | None = None
    update_command: Callable[..., int] | None = None


def _entry_path(deps: MutationDeps, store: Path, entry_id: str) -> Path:
    if deps.entry_path is None:
        return store / f"{entry_id}.json"
    return deps.entry_path(store, entry_id)


def _with_entry_lock(deps: MutationDeps, store: Path, entry_id: str):
    if deps.entry_lock is None:
        raise RuntimeError("mutation command requires an entry_lock dependency")
    return deps.entry_lock(_entry_path(deps, store, entry_id))


def cmd_update(args, *, deps: MutationDeps, lock_held: bool = False) -> int:
    """Apply one mutation or print the exact dry-run diff."""
    if args.commit and not lock_held:
        with _with_entry_lock(deps, args.store, args.id):
            return cmd_update(args, deps=deps, lock_held=True)

    refused = [
        field for field in deps.refused_update_fields
        if getattr(args, field, None) is not None
        or getattr(args, f"{field}_file", None) is not None
    ]
    if refused:
        flags = ", ".join(
            f"--{field}-file"
            if getattr(args, f"{field}_file", None) is not None
            else f"--{field}"
            for field in refused
        )
        print(
            f"[{'commit' if args.commit else 'dry-run'}] "
            f"{flags} cannot be changed: {', '.join(deps.digest_fields)} are the inputs "
            f"make_entry_id hashes, so editing one would decouple {args.id} from the "
            f"content its id is derived from.\n"
            f"  correcting the record  -> put the correction in --resolution\n"
            f"  a different problem    -> file it with `add`; a reworded problem "
            f"statement is a different entry\n"
            f"nothing was written.",
            file=sys.stderr,
        )
        return 64

    changes = {
        field: getattr(args, field, None)
        for field in deps.mutable_fields
        if getattr(args, field, None) is not None
    }
    clear_fields = tuple(getattr(args, "_clear_fields", ()))
    if (
        "acceptance_cmd" in changes
        and not str(changes["acceptance_cmd"] or "").strip()
    ):
        clear = list(clear_fields)
        for field in (
            "acceptance_cmd_static",
            "acceptance_expect_rc",
            "acceptance_green_expected",
        ):
            if field not in changes and field not in clear:
                clear.append(field)
        clear_fields = tuple(clear)
    if (
        "groomed_against" not in changes
        and any(
            changes.get(field) is not None for field in ("groomed_at", "groomed_by")
        )
    ):
        current_main = deps.main_commit() if deps.main_commit else None
        if current_main:
            changes["groomed_against"] = current_main
    if not changes and not clear_fields:
        print("nothing to change; pass at least one field", file=sys.stderr)
        return 64

    before = deps.load_entry(args.store, args.id)
    merged = deps.merged_and_validated(
        before, changes, args.id, clear_fields=clear_fields
    )
    acceptance = deps.gate_closure(before, changes, args.commit)

    if (
        changes.get("status") != "fixed"
        and str(changes.get("acceptance_cmd") or "").strip()
        and deps.report_pytest_selector_count is not None
    ):
        deps.report_pytest_selector_count(args.id, str(changes["acceptance_cmd"]))

    if args.commit:
        after = deps.update_entry(
            args.store,
            args.id,
            _clear_fields=clear_fields,
            _lock_held=lock_held,
            **changes,
        )
    else:
        after = merged

    changed_fields = [
        *changes,
        *(field for field in clear_fields if field not in changes),
    ]
    diff = {
        field: {"from": before.get(field, ""), "to": after.get(field, "")}
        for field in changed_fields
    }
    if args.json:
        import json

        print(
            json.dumps(
                {
                    "schema": f"kg.backlog.{args.command}.v1",
                    "mode": "commit" if args.commit else "dry-run",
                    "id": args.id,
                    "changes": diff,
                    "entry": after,
                    **({"acceptance": acceptance} if acceptance else {}),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"[{'commit' if args.commit else 'dry-run'}] {args.id}")
        for field, change in diff.items():
            print(
                f"  {field}: {str(change['from'])[:60]!r} -> "
                f"{str(change['to'])[:60]!r}"
            )
        if not args.commit:
            print("  (dry-run — pass --commit to land)")
    return 0


def cmd_groom(args, *, deps: MutationDeps, lock_held: bool = False) -> int:
    """Replace an executable grooming snapshot through the update engine."""
    if args.commit and not lock_held:
        with _with_entry_lock(deps, args.store, args.id):
            return cmd_groom(args, deps=deps, lock_held=True)

    before = deps.load_entry(args.store, args.id)
    if before.get("status") in ("fixed", "wont-fix"):
        raise deps.error_type(
            f"{args.id} is closed (status={before.get('status')}); `groom` never "
            "reopens closed tickets. If the problem recurred, file the new "
            "occurrence with `add` so the old closure remains an honest audit trail"
        )

    claims = deps.held_tickets() if deps.held_tickets else {}
    claim = claims.get(args.id)
    claim_path = str((claim or {}).get("path") or "")
    if claim and (
        not claim_path or Path(claim_path).resolve() != deps.root.resolve()
    ):
        raise deps.error_type(
            f"{args.id} is claimed by {claim.get('branch')} at "
            f"{claim_path or '(unknown path)'}; only the worktree owning a live "
            "claim may re-groom its executable spec"
        )

    proofs = [
        field
        for field in ("acceptance_cmd", "acceptance_manual")
        if str(getattr(args, field, None) or "").strip()
    ]
    if len(proofs) != 1:
        raise deps.error_type(
            "groom requires exactly one acceptance proof: acceptance_cmd for a "
            "machine-checkable gate OR acceptance_manual with the reason no "
            "command can express it"
        )

    if args.groomed_against:
        main_sha = deps.main_commit() if deps.main_commit else None
        against = str(args.groomed_against).strip()
        if main_sha is None:
            raise deps.error_type(
                "cannot validate --against because local main does not resolve; "
                "omit it to let groom capture local main automatically"
            )
        if deps.git is None:
            raise RuntimeError("groom --against requires a git dependency")
        ancestry = deps.git("merge-base", "--is-ancestor", against, main_sha)
        if ancestry.returncode != 0:
            raise deps.error_type(
                f"--against {against} is not reachable from local main {main_sha}; "
                "a grooming snapshot with no readable base cannot become dispatchable"
            )

    if proofs == ["acceptance_cmd"]:
        clear_fields = ["acceptance_manual"]
        if args.acceptance_cmd_static is None:
            clear_fields.append("acceptance_cmd_static")
        if args.acceptance_expect_rc is None:
            clear_fields.append("acceptance_expect_rc")
        if args.acceptance_green_expected is None:
            clear_fields.append("acceptance_green_expected")
    else:
        clear_fields = [
            "acceptance_cmd",
            "acceptance_cmd_static",
            "acceptance_expect_rc",
            "acceptance_green_expected",
        ]
    args._clear_fields = tuple(clear_fields)
    args.status = "triaged"
    args.groomed_at = args.groomed_at or (
        deps.today() if deps.today else None
    )

    update_command = deps.update_command or (
        lambda update_args, lock_held=False: cmd_update(
            update_args, deps=deps, lock_held=lock_held
        )
    )
    return update_command(args, lock_held=lock_held)
