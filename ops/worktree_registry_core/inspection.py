"""Read-only registry projections for humans and adapters."""

from __future__ import annotations

import argparse
import json
from typing import Any

from lib.worktree_scope import scope_problems

from .constants import EXIT_OK
from .environment import load_state, state_path
from .records import (
    SCHEMA,
    STATUS_ACTIVE,
    legacy_external_ids,
    norm_path,
    record_matches,
)


def record_view(record: dict[str, Any]) -> dict[str, Any]:
    view = dict(record)
    view["path"] = norm_path(str(view["path"])) if view.get("path") else None
    view["scope_status"] = (
        "known" if not scope_problems(view.get("scope")) else "unknown"
    )
    view["external_ids"] = legacy_external_ids(view)
    return view


def conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    holders: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("status") != STATUS_ACTIVE:
            continue
        for external_id in legacy_external_ids(record):
            holders.setdefault(external_id, []).append(
                {"branch": record.get("branch"), "path": record.get("path")}
            )
    return [
        {"external_id": key, "owners": owners}
        for key, owners in sorted(holders.items())
        if len(owners) > 1
    ]


def cmd_list(args: argparse.Namespace) -> int:
    target = state_path(args)
    state = load_state(target)
    selected = [record for record in state["records"] if isinstance(record, dict)]
    if args.active_only:
        selected = [
            record for record in selected if record.get("status") == STATUS_ACTIVE
        ]
    if args.branch:
        selected = [
            record for record in selected if record.get("branch") == args.branch
        ]
    if args.path:
        selected = [
            record for record in selected if record_matches(record, path=args.path)
        ]
    if args.external_id:
        selected = [
            record
            for record in selected
            if args.external_id in legacy_external_ids(record)
        ]
    if args.conflicts:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ledger": str(target),
                    "conflicts": conflicts(selected),
                    "problems": state.get("problems", []),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK
    if args.json:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ledger": str(target),
                    "records": [record_view(record) for record in selected],
                    "problems": state.get("problems", []),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK
    if not selected:
        print(f"(empty ledger: {target})")
        return EXIT_OK
    print("branch\texternal_ids\tstatus\tpath\tscope\tthread")
    for record in selected:
        print(
            "\t".join(
                [
                    str(record.get("branch") or "-"),
                    ",".join(legacy_external_ids(record)) or "-",
                    str(record.get("status") or "-"),
                    str(record.get("path") or "-"),
                    ("known" if not scope_problems(record.get("scope")) else "unknown"),
                    str(record.get("codex_thread_id") or "-"),
                ]
            )
        )
    return EXIT_OK
