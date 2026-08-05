#!/usr/bin/env python3
"""Backlog store — one file per entry, so N agents can file issues in parallel.

WHY THIS SHAPE
--------------
The predecessor was a single markdown table (`docs/runbook/improvement_backlog.md`).
It failed in three measured ways:

  * 54KB / 59 entries in one file. Filing one entry meant reading all of them;
    a plain read of it overflows a 25k-token budget.
  * Every append targets the same trailing region, so two worktrees appending
    concurrently conflict by construction.
  * Sequential ids collide. IMP-0017's own text records colliding twice with no
    parallelism at all. Across worktrees a counter cannot work even in
    principle — the entry files are invisible to each other until they merge,
    so both sides necessarily allocate the same next number.

So: one JSON file per entry, ids derived from content rather than allocated
from a counter. Two agents in two worktrees write disjoint paths and git merges
them with no conflict, which is the whole point.

Entries live under `docs/runbook/backlog/` as `.json` and NOT as `.md` on
purpose: `ops/docs_lint.sh:216` scans every `docs/**/*.md` and demands a
`<!-- doc-meta -->` block with a reachable `verified_against`. Storing 59
ledger rows as markdown would manufacture 59 doc-meta liabilities. Keeping them
as `.json` costs nothing and needs no carve-out in the lint tool.

JSON rather than YAML because there is no YAML dependency anywhere in `ops/`
(`docs_impact.py` and `ui_quality_plane.py` both hand-parse), and the
`ops/**.py` cutover gate runs tests under a sandbox `uv run --no-project --with
pytest` with no project dependencies available. Hand-rolling a YAML subset
parser to store a ledger whose own contents are largely "a tool lied to us"
would be a poor trade.

Note the serialisation here is the *readable* form (indent=2, sorted keys), not
the canonical hashing form used by `ops/app_review_gate.py` and friends. These
files are reviewed by humans and diffed by git; they are not hashed artifacts.
See IMP-0042 for the separate canonical-JSON consolidation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "docs" / "runbook" / "backlog"

SCHEMA = "kg.backlog.entry.v1"

# Two streams, deliberately kept apart. IMP is harness/tooling friction owned by
# platform-steward; APP is what a user hits while actually using the app, owned
# by the ios/backend line departments. Mixing them makes platform-steward's
# triage queue unreadable, which is the reason for the split.
STREAMS = ("IMP", "APP")

CATEGORIES = {
    "IMP": ("tool", "cli", "doc", "arch"),
    "APP": ("ux", "correctness", "perf", "data", "content"),
}

SEVERITIES = ("low", "med", "high")
STATUSES = ("open", "triaged", "in-progress", "fixed", "wont-fix")

REQUIRED_FIELDS = (
    "schema",
    "id",
    "stream",
    "date",
    "source",
    "category",
    "severity",
    "status",
    "detail",
    "resolution",
)

# Fields that only make sense for an app-usage report. An IMP entry carrying a
# `surface` means someone filed an app problem into the tooling stream.
APP_ONLY_FIELDS = ("surface", "repro", "build")


class BacklogError(Exception):
    """Raised for usage errors that should exit 64 rather than traceback."""


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------

def make_entry_id(*, stream: str, date: str, source: str, detail: str) -> str:
    """Content-derived id: `<STREAM>-<YYYYMMDD>-<6 hex>`.

    Content-derived rather than random for one concrete reason: the importer
    that migrates the legacy table is re-runnable, and re-running it while the
    source file is still being edited must converge on the same ids rather than
    fork a second copy of every entry.

    The digest covers the fields that identify *which problem this is* —
    stream, date, source, detail. Mutable state (status, severity, resolution)
    is excluded so that triaging an entry never changes its id.
    """
    payload = "\x1f".join([stream, date, source, detail]).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:6]
    return f"{stream}-{date.replace('-', '')}-{digest}"


def entry_path(store: Path, entry_id: str) -> Path:
    return Path(store) / f"{entry_id}.json"


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------

def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a crash cannot publish a partial
    entry. Callers rely on this: a truncated JSON entry would make the whole
    store unreadable to `render`, and the failure would surface far from the
    write that caused it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _check_vocabulary(payload: dict) -> list[dict]:
    problems: list[dict] = []
    stream = payload.get("stream")

    if stream not in STREAMS:
        problems.append({"kind": "bad-stream", "value": stream})
    elif payload.get("category") not in CATEGORIES[stream]:
        # Only meaningful once the stream is known — the vocabularies differ.
        problems.append({"kind": "bad-category", "value": payload.get("category")})

    if payload.get("severity") not in SEVERITIES:
        problems.append({"kind": "bad-severity", "value": payload.get("severity")})
    if payload.get("status") not in STATUSES:
        problems.append({"kind": "bad-status", "value": payload.get("status")})

    return problems


def validate_entry(payload: dict, *, entry_id: str | None = None) -> list[dict]:
    problems: list[dict] = []

    for field in REQUIRED_FIELDS:
        if field not in payload:
            problems.append({"kind": "missing-field", "field": field})

    if entry_id is not None and payload.get("id") != entry_id:
        # The filename is how every other entry refers to this one. If the two
        # drift, `show <id>` and the generated view disagree about what exists.
        problems.append(
            {
                "kind": "id-filename-drift",
                "filename_id": entry_id,
                "payload_id": payload.get("id"),
            }
        )

    problems.extend(_check_vocabulary(payload))

    if payload.get("stream") == "IMP":
        for field in APP_ONLY_FIELDS:
            if payload.get(field):
                problems.append({"kind": "app-field-on-imp-entry", "field": field})

    return problems


def validate_store(store: Path) -> list[dict]:
    store = Path(store)
    problems: list[dict] = []
    if not store.exists():
        return problems

    for path in sorted(store.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append({"kind": "unparseable", "path": str(path), "error": str(exc)})
            continue
        if not isinstance(payload, dict):
            problems.append({"kind": "unparseable", "path": str(path), "error": "not an object"})
            continue
        for problem in validate_entry(payload, entry_id=path.stem):
            problems.append({**problem, "path": str(path)})

    return problems


# ---------------------------------------------------------------------------
# store operations
# ---------------------------------------------------------------------------

def add_entry(
    store: Path,
    *,
    stream: str,
    date: str,
    source: str,
    category: str,
    severity: str,
    status: str,
    detail: str,
    resolution: str = "",
    surface: str | None = None,
    repro: str | None = None,
    build: str | None = None,
    entry_id: str | None = None,
) -> dict:
    """Create one entry file and return the entry.

    Deliberately NOT dry-run-by-default, unlike the mutation subcommands.
    Creating a new file is additive and trivially reversible with git, and
    forcing two calls to file one issue is precisely the kind of friction that
    makes agents route around a tool. The exception is stated in `--help` rather
    than left for the next caller to discover — IMP-0040 is that lesson.
    """
    payload = {
        "schema": SCHEMA,
        "stream": stream,
        "date": date,
        "source": source,
        "category": category,
        "severity": severity,
        "status": status,
        "detail": detail,
        "resolution": resolution,
    }
    for field, value in (("surface", surface), ("repro", repro), ("build", build)):
        if value:
            payload[field] = value

    payload["id"] = entry_id or make_entry_id(
        stream=stream, date=date, source=source, detail=detail
    )

    problems = validate_entry(payload, entry_id=payload["id"])
    if problems:
        raise ValueError(f"invalid entry: {problems}")

    _write_atomic(entry_path(store, payload["id"]), _dumps(payload))
    return payload


def load_entry(store: Path, entry_id: str) -> dict:
    path = entry_path(store, entry_id)
    if not path.exists():
        raise KeyError(entry_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_entries(store: Path):
    store = Path(store)
    if not store.exists():
        return
    for path in sorted(store.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict):
            yield payload


def _sort_key(payload: dict) -> tuple:
    # (date, id) rather than filesystem order, so the generated view is stable
    # across machines and reruns.
    return (str(payload.get("date", "")), str(payload.get("id", "")))


def entry_sort_key_by_id(store: Path):
    """Return a key function over entry ids, matching `list_entries` order."""
    index = {payload.get("id"): _sort_key(payload) for payload in _iter_entries(store)}
    return lambda entry_id: index.get(entry_id, ("", entry_id))


def list_entries(
    store: Path,
    *,
    status: str | None = None,
    stream: str | None = None,
    severity: str | None = None,
    category: str | None = None,
) -> list[dict]:
    wanted = {
        "status": status,
        "stream": stream,
        "severity": severity,
        "category": category,
    }
    hits = [
        payload
        for payload in _iter_entries(store)
        if all(value is None or payload.get(field) == value for field, value in wanted.items())
    ]
    return sorted(hits, key=_sort_key)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_store_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE,
        help=f"entry directory (default: {DEFAULT_STORE.relative_to(ROOT)})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backlog.py",
        description="Backlog store: one file per entry, safe for concurrent agents.",
        epilog=(
            "dry-run contract: `add` lands immediately (additive, git-reversible); "
            "mutations that overwrite existing entries are dry-run by default and "
            "need --commit."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="file a new entry (lands immediately)")
    _add_store_arg(p_add)
    p_add.add_argument("--stream", choices=STREAMS, required=True)
    p_add.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_add.add_argument("--source", required=True, help="where this was noticed")
    p_add.add_argument("--category", required=True, help=f"IMP: {CATEGORIES['IMP']} APP: {CATEGORIES['APP']}")
    p_add.add_argument("--severity", choices=SEVERITIES, required=True)
    p_add.add_argument("--status", choices=STATUSES, default="open")
    p_add.add_argument("--detail", required=True)
    p_add.add_argument("--resolution", default="")
    p_add.add_argument("--surface", help="APP only: reader/vocabulary/notebook/...")
    p_add.add_argument("--repro", help="APP only: how to reproduce")
    p_add.add_argument("--build", help="APP only: build the problem was seen on")
    p_add.add_argument("--id", dest="entry_id", help="explicit id (migration of legacy IMP-#### only)")
    p_add.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="list entries")
    _add_store_arg(p_list)
    p_list.add_argument("--status", choices=STATUSES)
    p_list.add_argument("--stream", choices=STREAMS)
    p_list.add_argument("--severity", choices=SEVERITIES)
    p_list.add_argument("--category")
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="show one entry")
    _add_store_arg(p_show)
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")

    p_validate = sub.add_parser("validate", help="schema-check every entry")
    _add_store_arg(p_validate)
    p_validate.add_argument("--json", action="store_true")

    return parser


def _cmd_add(args) -> int:
    entry = add_entry(
        args.store,
        stream=args.stream,
        date=args.date,
        source=args.source,
        category=args.category,
        severity=args.severity,
        status=args.status,
        detail=args.detail,
        resolution=args.resolution,
        surface=args.surface,
        repro=args.repro,
        build=args.build,
        entry_id=args.entry_id,
    )
    if args.json:
        print(json.dumps({"schema": "kg.backlog.add.v1", "entry": entry}, ensure_ascii=False))
    else:
        print(f"{entry['id']}  [{entry['stream']}/{entry['category']}/{entry['severity']}]")
        print(f"  {entry['detail'][:120]}")
    return 0


def _cmd_list(args) -> int:
    entries = list_entries(
        args.store,
        status=args.status,
        stream=args.stream,
        severity=args.severity,
        category=args.category,
    )
    if args.json:
        print(json.dumps({"schema": "kg.backlog.list.v1", "entries": entries}, ensure_ascii=False))
        return 0
    for entry in entries:
        print(
            f"{entry['id']:<24} {entry['status']:<12} {entry['severity']:<5} "
            f"{entry['category']:<12} {entry['detail'][:70]}"
        )
    print(f"\n{len(entries)} entries")
    return 0


def _cmd_show(args) -> int:
    try:
        entry = load_entry(args.store, args.id)
    except KeyError:
        print(f"no such entry: {args.id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"schema": "kg.backlog.show.v1", "entry": entry}, ensure_ascii=False))
        return 0
    for field in REQUIRED_FIELDS + APP_ONLY_FIELDS:
        if field in entry and field != "schema":
            print(f"{field:<12} {entry[field]}")
    return 0


def _cmd_validate(args) -> int:
    problems = validate_store(args.store)
    if args.json:
        print(
            json.dumps(
                {"schema": "kg.backlog.validate.v1", "problems": problems, "ok": not problems},
                ensure_ascii=False,
            )
        )
    else:
        for problem in problems:
            print(f"ERROR {problem.get('path', '')} — {problem['kind']} {problem}")
        print(f"{len(problems)} problems")
    return 2 if problems else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "add": _cmd_add,
        "list": _cmd_list,
        "show": _cmd_show,
        "validate": _cmd_validate,
    }
    try:
        return handlers[args.command](args)
    except (BacklogError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    sys.exit(main())
