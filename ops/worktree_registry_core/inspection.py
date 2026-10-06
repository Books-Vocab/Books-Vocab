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
    try:
        view["external_ids"] = legacy_external_ids(view)
    except (TypeError, ValueError):
        # Problems carry the authoritative diagnostic.  The projection stays
        # readable without mutating or pretending to repair the ledger fact.
        view["external_ids"] = []
    return view


def conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    holders: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("status") != STATUS_ACTIVE:
            continue
        try:
            record_external_ids = legacy_external_ids(record)
        except (TypeError, ValueError):
            continue
        for external_id in record_external_ids:
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
    selected = [
        (index, record)
        for index, record in enumerate(state["records"])
        if isinstance(record, dict)
    ]
    if args.active_only:
        selected = [
            (index, record)
            for index, record in selected
            if record.get("status") == STATUS_ACTIVE
        ]
    if args.branch:
        selected = [
            (index, record)
            for index, record in selected
            if record.get("branch") == args.branch
        ]
    if args.path:
        selected = [
            (index, record)
            for index, record in selected
            if record_matches(record, path=args.path)
        ]
    if args.external_id:
        selected = [
            (index, record)
            for index, record in selected
            if args.external_id in _readable_external_ids(record)
        ]
    selected_indexes = {index for index, _ in selected}
    selected_records = [record for _, record in selected]
    selected_problems = _problems_for_selection(state, selected_indexes)
    if args.conflicts:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ledger": str(target),
                    "conflicts": conflicts(selected_records),
                    "problems": selected_problems,
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
                    "records": [record_view(record) for record in selected_records],
                    "problems": selected_problems,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK
    if not selected_records:
        print(f"(empty ledger: {target})")
        return EXIT_OK
    print("branch\texternal_ids\tstatus\tpath\tscope\tthread")
    for record in selected_records:
        print(
            "\t".join(
                [
                    str(record.get("branch") or "-"),
                    ",".join(_readable_external_ids(record)) or "-",
                    str(record.get("status") or "-"),
                    str(record.get("path") or "-"),
                    ("known" if not scope_problems(record.get("scope")) else "unknown"),
                    str(record.get("codex_thread_id") or "-"),
                ]
            )
        )
    return EXIT_OK


def _problems_for_selection(
    state: dict[str, Any], selected_indexes: set[int]
) -> list[dict[str, Any]]:
    """Project record-scoped diagnostics with the same selector as records.

    Unknown diagnostics remain visible because an unresolvable record identity
    is itself a fail-closed fact.  Known record diagnostics follow the selected
    record set, so ``--active-only`` does not present terminal history as an
    active ownership problem.
    """

    records = state.get("records", [])
    selected_problems: list[dict[str, Any]] = []
    for problem in state.get("problems", []):
        index = problem.get("index")
        if (
            type(index) is not int
            or index < 0
            or index >= len(records)
            or not isinstance(records[index], dict)
            or index in selected_indexes
        ):
            selected_problems.append(problem)
    return selected_problems


def _readable_external_ids(record: dict[str, Any]) -> list[str]:
    try:
        return legacy_external_ids(record)
    except (TypeError, ValueError):
        return []
