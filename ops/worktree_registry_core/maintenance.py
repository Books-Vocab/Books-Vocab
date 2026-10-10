"""Read-only orphan and ghost audit and lossless registry compaction."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .constants import EXIT_OK, EXIT_USAGE
from .environment import git, load_state, repo_root, state_path
from .inspection import record_view
from .records import (
    SCHEMA,
    TERMINAL_STATUSES,
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


def ghost_facts(record: dict[str, Any]) -> dict[str, Any] | None:
    """The CAS guards that retire a ghost lane, or None if it is not a ghost.

    A ghost is an active claim whose worktree directory is gone, that never
    handed back, and whose branch carries no commit beyond origin/main (#2771).
    ``expected_head_sha`` is the head ``resolve`` compares against: the local
    branch tip, else the recorded base commit.
    """
    if record.get("status") != "active" or not record.get("path"):
        return None
    if os.path.exists(str(record["path"])):
        return None
    if record.get("handed_back_sha") or record.get("handed_back_at"):
        return None
    branch = str(record.get("branch") or "")
    head = None
    if branch:
        rc, out = git(
            ["rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}"], repo_root()
        )
        head = out.strip() if rc == 0 else None
    if head:
        rc, out = git(["rev-list", "--count", f"origin/main..{head}"], repo_root())
        if rc != 0 or out.strip() != "0":
            return None
    else:
        head = record.get("base_sha") or record.get("base")
    if not head:
        return None
    return {
        "branch": record.get("branch"),
        "path": record.get("path"),
        "claim_generation": record.get("claim_generation"),
        "expected_head_sha": head,
    }


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
        "ghosts": [facts for r in orphaned if (facts := ghost_facts(r))],
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
    """Compact record shape without discarding immutable terminal audit evidence."""
    target = state_path(args)
    state = load_state(target)
    retained = [compact_record(record) for record in retained_records(state)]
    removed = len(state.get("records", [])) - len(retained)
    non_terminal_preserved = sum(
        record.get("status") not in TERMINAL_STATUSES for record in retained
    )
    terminal_preserved = len(retained) - non_terminal_preserved
    payload = {
        "schema": SCHEMA,
        "action": "compact",
        "non_terminal_preserved": non_terminal_preserved,
        "terminal_records_preserved": terminal_preserved,
        "terminal_records_removed": 0,
        "records_removed": removed,
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
        non_terminal_preserved = sum(
            record.get("status") not in TERMINAL_STATUSES for record in retained
        )
        payload["non_terminal_preserved"] = non_terminal_preserved
        payload["terminal_records_preserved"] = len(retained) - non_terminal_preserved
        payload["terminal_records_removed"] = 0
        payload["records_removed"] = removed
        payload["action"] = "compact-committed"
    print(
        json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json
        else json.dumps(payload, ensure_ascii=False)
    )
    return EXIT_OK
