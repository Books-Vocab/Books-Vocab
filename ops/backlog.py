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
import re
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "docs" / "runbook" / "backlog"
DEFAULT_VIEW = ROOT / "docs" / "runbook" / "improvement_backlog.md"

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
    verdict_fields: dict | None = None,
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
    for field, value in (verdict_fields or {}).items():
        if field not in VERDICT_FIELDS:
            raise ValueError(f"unknown verdict field: {field}")
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
# legacy table import
# ---------------------------------------------------------------------------

LEGACY_COLUMNS = ("id", "date", "source", "category", "severity", "status", "detail", "resolution")

_ID_RE = re.compile(r"^(?:IMP|APP)-(?:\d{4}|\d{8}-[0-9a-f]{6})$")

_EMPTY_CELL = "—"


def _split_row_raw(line: str) -> list[str]:
    """Split a markdown table row on UNESCAPED pipes, WITHOUT cleaning cells.

    IMP-0023's detail contains a literal `\\|\\| true`. Splitting on a naive `|`
    tears that row into the wrong number of columns, which either drops the
    entry or shifts every field after it by one — silently, in both cases.

    Cells come back raw because recovery (below) has to rejoin them, and
    stripping first would silently eat the whitespace around an unescaped pipe:
    `` `|| true` `` would come back as `` `||true` ``.
    """
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return parts


def _clean(cell: str) -> str:
    return cell.strip().replace("\\|", "|")


def _recover_overflowing_row(raw_cells: list[str]) -> list[str] | None:
    """Rebuild a row that has too many columns because a cell contains an
    unescaped `|`.

    Anchored on the three controlled-vocabulary columns (category, severity,
    status) plus the id, all of which are short and closed sets. If those line
    up, everything between `status` and the final column is the detail, which is
    the only free-prose field long enough to attract stray pipes. If they do not
    line up we return None and the caller reports the row rather than guessing —
    an enumerated hole beats an anonymous one.
    """
    if len(raw_cells) <= len(LEGACY_COLUMNS):
        return None

    head = [_clean(c) for c in raw_cells[:6]]
    known_categories = {c for cats in CATEGORIES.values() for c in cats}
    if head[3] not in known_categories or head[4] not in SEVERITIES or head[5] not in STATUSES:
        return None

    detail = _clean("|".join(raw_cells[6:-1]))
    resolution = _clean(raw_cells[-1])
    return head + [detail, resolution]


def parse_legacy_table(text: str) -> tuple[list[dict], list[dict]]:
    """Parse the legacy 8-column ledger table.

    Returns (rows, problems). A row that cannot be understood goes into
    `problems` and is never silently discarded: a migration that quietly loses
    four entries out of 59 is indistinguishable from one that worked.

    APP-* rows are skipped rather than reported. The legacy table predates the
    APP stream entirely, so an APP row can only come from the *generated* view's
    own second table, which has a different column set.
    """
    rows: list[dict] = []
    problems: list[dict] = []

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        raw_cells = _split_row_raw(line)
        if not raw_cells or not _ID_RE.match(_clean(raw_cells[0])):
            continue  # header, separator, or a prose table
        cells = [_clean(c) for c in raw_cells]
        if cells[0].startswith("APP-"):
            continue

        if len(cells) > len(LEGACY_COLUMNS):
            rebuilt = _recover_overflowing_row(raw_cells)
            if rebuilt is None:
                problems.append(
                    {
                        "kind": "malformed-row",
                        "id": cells[0],
                        "line": lineno,
                        "columns": len(cells),
                        "expected": len(LEGACY_COLUMNS),
                    }
                )
                continue
            cells = rebuilt
            problems.append(
                {
                    "kind": "recovered-row",
                    "id": cells[0],
                    "line": lineno,
                    "note": "unescaped '|' in a cell; detail rejoined using the "
                    "controlled-vocabulary columns as anchors — verify the "
                    "detail/resolution boundary",
                }
            )
        elif len(cells) < len(LEGACY_COLUMNS):
            problems.append(
                {
                    "kind": "malformed-row",
                    "id": cells[0],
                    "line": lineno,
                    "columns": len(cells),
                    "expected": len(LEGACY_COLUMNS),
                }
            )
            continue

        # No `_recovered` marker on the row itself: the problem list already
        # names it, and an extra key here would make a recovered row compare
        # unequal to its own re-parsed render.
        row = dict(zip(LEGACY_COLUMNS, cells))
        if row["resolution"] == _EMPTY_CELL:
            row["resolution"] = ""
        rows.append(row)

    return rows, problems


# ---------------------------------------------------------------------------
# verdict stamps
# ---------------------------------------------------------------------------
#
# The 2026-08-05 re-verification sweep encoded its results as a convention
# inside the resolution cell:
#
#   —(YYYY-MM-DD 驗證 <VERDICT>;落點 `file:line`,成本 <S|M|L|S–M>,測試…)
#
# Promoting those to real fields is the point of having a store. Extraction is
# ADDITIVE and LOSSLESS — `resolution` keeps the original text verbatim and
# remains authoritative — so a stamp this parser does not recognise costs an
# empty field and a named report, never a lost sentence.

# The stamp is the ADJACENCY `YYYY-MM-DD 驗證 <VERDICT>`, matched as one unit.
#
# Two bugs came from not doing this. Anchoring the date on `—(` missed
# IMP-0029, whose stamp starts with prose (`—(by-design,待產品決策;2026-08-05
# 驗證 …`) — the date is regular only relative to 驗證, not to the bracket. And
# gating extraction on "does the text contain 驗證" reported three entries as
# having unreadable stamps when they simply mention the word in prose: a
# keyword standing in for the structure, which is the same proxy mistake this
# module refuses to make elsewhere.
#
# Digits belong in the verdict token: `DUPLICATE-OF-IMP-0042` ends in an id, and
# without them the pattern stops before the digits and fails its own lookahead.
_STAMP_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*驗證\s+([A-Z][A-Z0-9-]*)(?=[;,:，、。\s)]|$)"
)
_DUPLICATE_RE = re.compile(r"^DUPLICATE-OF-(IMP-\d+)$")
# `成本 S–M` uses an EN DASH (U+2013). Splitting on `-` would report `S` and
# silently halve the estimate, so the range is matched whole.
_COST_RE = re.compile(r"成本\s*([SML](?:[–-][SML])?)")
_FIX_SITE_RE = re.compile(r"落點\s*`([^`]+)`")
_FIX_SITE_PRESENT_RE = re.compile(r"落點\s*")


def extract_verdict_fields(resolution: str) -> tuple[dict, list[dict]]:
    """Pull the structured stamp out of a resolution cell.

    Returns (fields, misses). `misses` names each field that looked present but
    could not be read confidently — the caller reports those rather than
    guessing, because a guessed `fix_site` becomes a path that later readers
    trust.

    `needs_test` is deliberately NOT extracted: the sweep recorded testing
    intent in free prose with no consistent encoding, and deriving a boolean
    from the presence of the word 測試 would be a proxy standing in for the
    property rather than the property itself.
    """
    fields: dict = {}
    misses: list[dict] = []

    text = resolution or ""
    stamp = _STAMP_RE.search(text)
    if not stamp:
        # No stamp. Either a plain commit hash (the majority) or prose that
        # happens to use the word 驗證. Neither is a miss, and reporting them
        # would bury the real ones in noise.
        return fields, misses

    fields["verified_at"] = stamp.group(1)
    verdict = stamp.group(2).rstrip("-")
    fields["verdict"] = verdict
    duplicate = _DUPLICATE_RE.match(verdict)
    if duplicate:
        fields["duplicate_of"] = duplicate.group(1)

    cost_match = _COST_RE.search(text)
    if cost_match:
        fields["cost"] = cost_match.group(1)

    fix_match = _FIX_SITE_RE.search(text)
    if fix_match:
        fields["fix_site"] = fix_match.group(1)
    elif _FIX_SITE_PRESENT_RE.search(text):
        # `落點` followed by free prose has no delimiter that can be trusted.
        misses.append({"field": "fix_site", "reason": "落點 present but not a backticked token"})

    return fields, misses


VERDICT_FIELDS = ("verified_at", "verdict", "cost", "fix_site", "duplicate_of")


def import_legacy(text: str, store: Path) -> dict:
    """Import the legacy table into the store. Re-runnable and idempotent.

    Re-runnable is a hard requirement, not a nicety: the source table is still
    being edited by other sessions while this migration is in flight, so the
    real import runs last, against a file that moved underneath it. Ids are
    carried over verbatim — the table cross-references them in prose ("see
    IMP-0052"), and renumbering would break every one of those references.

    Entries already in the store that are absent from the table are left alone,
    so importing the IMP table never disturbs APP entries filed via `add`.
    """
    rows, problems = parse_legacy_table(text)
    imported = 0

    for row in rows:
        verdict_fields, misses = extract_verdict_fields(row["resolution"])
        for miss in misses:
            problems.append({"kind": "stamp-not-read", "id": row["id"], **miss})
        try:
            add_entry(
                store,
                entry_id=row["id"],
                stream=row["id"].split("-", 1)[0],
                date=row["date"],
                source=row["source"],
                category=row["category"],
                severity=row["severity"],
                status=row["status"],
                detail=row["detail"],
                resolution=row["resolution"],
                verdict_fields=verdict_fields,
            )
        except ValueError as exc:
            # Record and keep going. Dying mid-import would leave a partial
            # store, which is worse than a complete store plus a problem list.
            problems.append({"kind": "rejected-row", "id": row["id"], "error": str(exc)})
            continue
        imported += 1

    return {"imported": imported, "problems": problems}


# ---------------------------------------------------------------------------
# generated view
# ---------------------------------------------------------------------------

# `tier: runbook` and not `tier: generated`: `generated` is a registry *kind*
# (docs/registry.yml), while the frontmatter `tier` is checked against
# docs_lint.sh's VALID_TIERS, which has no such value. The precedent is
# docs/snapshot/ios_baseline.md — tier: snapshot in the doc, kind: generated in
# the registry.
_VIEW_HEADER = """<!-- doc-meta
tier: runbook
authority: generated
update_trigger: machine-generated
scope:
  - docs/runbook/backlog/
verified_against: {verified_against}
-->
# 改善 Backlog（kaizen ledger）

> ⚠️ **GENERATED — 不要手改這個檔。** 內容由 `ops/backlog.py render` 從
> `docs/runbook/backlog/*.json` 產生，手改會被下一次 render 覆蓋。
> 要改請用 `ops/backlog.py update <id>`；要新增用 `ops/backlog.py add`。

> 自我提升迴圈的 **SoT**：所有「工具 / CLI / 文檔 / 架構」摩擦（`IMP-*`）與
> 「app 實際使用」問題（`APP-*`）的 open 問題單一登記處。
> 原則見**鐵律9**（摩擦優先修工具）、分級見 `kg-router`「Tool Friction」、
> 表態見 `kg-receipt`「Tooling Debt」——本文**不複述**，只負責**持久化、追蹤、收斂**。

## 為什麼是一筆一檔

receipt 裡的 tooling debt 會隨 transcript 蒸發。本 ledger 讓每個 raised 問題
**進 git、可回溯、有 owner、追到 resolved**。

存成 `docs/runbook/backlog/<id>.json`（一筆一檔）而非單一表格，是因為單一表格
在多 agent 並發下必然衝突：每次 append 都打同一段行區，而流水號 id 跨 worktree
必撞（檔案在 merge 前彼此看不見）。IMP-0017 自己記著已經撞過兩次。

## Entry schema

- `status`：`open` → `triaged` → `in-progress` → `fixed` / `wont-fix`（附理由）
- `category`：IMP 為 `tool` / `cli` / `doc` / `arch`；APP 為 `ux` / `correctness` / `perf` / `data` / `content`
- `severity`：`low` / `med` / `high`
- `resolution`：解決 commit hash，或 wont-fix 理由（這是「可回溯」的關鍵欄）
- 新 id 為 `<STREAM>-<YYYYMMDD>-<hash6>`，內容衍生、不用流水號；既有 `IMP-####` 沿用不改號
"""

_IMP_INTRO = """
## IMP — 工具 / CLI / 文檔 / 架構摩擦

owner = `platform-steward`。andon 規則見 `kg-receipt`「Tooling Debt」。
"""

_APP_INTRO = """
## APP — app 實際使用問題

owner = 對應 Line 部門（`ios-engineer` / `backend-engineer`）。
與 IMP 分流的理由：分類詞彙、owner、發現途徑都不同，混在同一條 queue 會讓
platform-steward 的 triage 失效。
"""


def _cell(value: str) -> str:
    """Make a value safe to sit inside a markdown table cell."""
    text = str(value or "")
    text = text.replace("\n", " ").replace("\r", " ")
    return text.replace("|", "\\|")


def _render_table(entries: list[dict], columns: tuple[str, ...]) -> str:
    head = "| " + " | ".join(columns) + " |\n"
    sep = "|" + "|".join("---" for _ in columns) + "|\n"
    body = ""
    for entry in entries:
        cells = [_cell(entry.get(col, "")) or _EMPTY_CELL for col in columns]
        body += "| " + " | ".join(cells) + " |\n"
    return head + sep + body


APP_COLUMNS = (
    "id",
    "date",
    "source",
    "surface",
    "category",
    "severity",
    "status",
    "detail",
    "repro",
    "build",
    "resolution",
)


def render_view(store: Path, *, verified_against: str) -> str:
    """Render the human-readable view of the store. Deterministic."""
    imp = list_entries(store, stream="IMP")
    app = list_entries(store, stream="APP")

    out = _VIEW_HEADER.format(verified_against=verified_against)
    out += _IMP_INTRO + "\n" + _render_table(imp, LEGACY_COLUMNS)
    out += _APP_INTRO + "\n" + _render_table(app, APP_COLUMNS)
    out += f"\n<!-- {len(imp)} IMP + {len(app)} APP entries -->\n"
    return out


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

    p_import = sub.add_parser(
        "import",
        help="import the legacy markdown table into the store (re-runnable, idempotent)",
    )
    _add_store_arg(p_import)
    p_import.add_argument("--from", dest="source_doc", type=Path, default=DEFAULT_VIEW)
    p_import.add_argument("--commit", action="store_true", help="actually write (default: dry-run)")
    p_import.add_argument("--json", action="store_true")

    p_render = sub.add_parser("render", help="regenerate the human-readable view from the store")
    _add_store_arg(p_render)
    p_render.add_argument("--out", type=Path, default=DEFAULT_VIEW)
    p_render.add_argument("--verified-against", help="commit sha for doc-meta (default: HEAD)")
    p_render.add_argument("--commit", action="store_true", help="actually write (default: stdout)")
    p_render.add_argument("--json", action="store_true")

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


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _cmd_import(args) -> int:
    text = args.source_doc.read_text(encoding="utf-8")

    if not args.commit:
        # Dry-run into a throwaway store so the reported counts come from the
        # real code path rather than a separate estimate that could disagree.
        with tempfile.TemporaryDirectory() as tmp:
            result = import_legacy(text, Path(tmp) / "backlog")
        result["mode"] = "dry-run"
    else:
        result = import_legacy(text, args.store)
        result["mode"] = "commit"

    result["source"] = str(args.source_doc)
    if args.json:
        print(json.dumps({"schema": "kg.backlog.import.v1", **result}, ensure_ascii=False))
    else:
        print(f"[{result['mode']}] imported {result['imported']} entries from {args.source_doc}")
        for problem in result["problems"]:
            print(f"  {problem['kind']}: {problem.get('id', '?')} — {problem.get('note', problem)}")
    # Recovered rows are advisory; only rows that could not be taken are a
    # failure, because those are entries that would vanish.
    lost = [p for p in result["problems"] if p["kind"] in ("malformed-row", "rejected-row")]
    return 2 if lost else 0


def _cmd_render(args) -> int:
    verified = args.verified_against or _git_head()
    text = render_view(args.store, verified_against=verified)

    if args.commit:
        _write_atomic(args.out, text)
        if args.json:
            print(
                json.dumps(
                    {"schema": "kg.backlog.render.v1", "out": str(args.out), "bytes": len(text)},
                    ensure_ascii=False,
                )
            )
        else:
            print(f"wrote {args.out} ({len(text)} bytes, verified_against={verified})")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "add": _cmd_add,
        "list": _cmd_list,
        "show": _cmd_show,
        "validate": _cmd_validate,
        "import": _cmd_import,
        "render": _cmd_render,
    }
    try:
        return handlers[args.command](args)
    except (BacklogError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    sys.exit(main())
