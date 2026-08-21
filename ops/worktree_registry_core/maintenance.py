"""Read-only orphan audit and exact terminal-history compaction."""

from __future__ import annotations

import argparse
import json
import sys

from .constants import EXIT_OK, EXIT_USAGE
from .environment import git, load_state, repo_root, state_path
from .inspection import record_view
from .records import (
    SCHEMA,
    active_records,
    compact_record,
    mutation_blockers,
    norm_path,
    retained_records,
)
from .storage import ledger_lock, save_state


def worktree_rows() -> list[dict[str, str | None]]:
    rc, out = git(["worktree", "list", "--porcelain"], repo_root())
    if rc != 0:
        return []
    rows: list[dict[str, str | None]] = []
    current: dict[str, str | None] = {}
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            if current:
                rows.append(current)
            current = {"path": line[9:]}
        elif line.startswith("branch "):
            current["branch"] = line[7:].removeprefix("refs/heads/")
        elif line == "" and current:
            rows.append(current)
            current = {}
    return rows


def cmd_sweep(args: argparse.Namespace) -> int:
    if args.commit:
        print(
            "✗ bulk sweep mutation is disabled; use exact resolve CAS per record",
            file=sys.stderr,
        )
        return EXIT_USAGE
    target = state_path(args)
    state = load_state(target)
    known = {
        norm_path(str(row.get("path"))) for row in worktree_rows() if row.get("path")
    }
    orphaned = [
        record
        for record in active_records(state)
        if record.get("path") and norm_path(str(record["path"])) not in known
    ]
    payload = {
        "schema": SCHEMA,
        "action": "sweep",
        "orphaned": [record_view(record) for record in orphaned],
        "commit": bool(args.commit),
    }
    print(
        json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json
        else (
            "✓ no orphaned registry records"
            if not orphaned
            else "\n".join(
                f"! orphaned: {record.get('branch')} {record.get('path')}"
                for record in orphaned
            )
        )
    )
    return EXIT_OK


def cmd_compact(args: argparse.Namespace) -> int:
    """Retain every non-terminal claim and remove terminal history only."""
    target = state_path(args)
    state = load_state(target)
    retained = [compact_record(record) for record in retained_records(state)]
    removed = len(state.get("records", [])) - len(retained)
    payload = {
        "schema": SCHEMA,
        "action": "compact",
        "non_terminal_preserved": len(retained),
        "terminal_records_removed": removed,
        "commit": bool(args.commit),
    }
    if args.commit:
        with ledger_lock(target):
            state = load_state(target)
            blockers = mutation_blockers(state)
            if blockers:
                print(
                    "✗ malformed ownership facts block registry compaction",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            retained = [compact_record(record) for record in retained_records(state)]
            removed = len(state.get("records", [])) - len(retained)
            save_state(target, {"schema": SCHEMA, "records": retained})
        payload["non_terminal_preserved"] = len(retained)
        payload["terminal_records_removed"] = removed
        payload["action"] = "compact-committed"
    print(
        json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json
        else json.dumps(payload, ensure_ascii=False)
    )
    return EXIT_OK
