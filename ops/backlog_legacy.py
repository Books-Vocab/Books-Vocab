"""Legacy markdown-table migration helpers for the backlog.

The current backlog is a JSON file store.  This module keeps the historical
8-column importer and its lossless verdict-stamp extraction isolated from the
active entry schema and CLI.  Store access is callback-based so migration
tests and the CLI can share the parser without importing the whole backlog
module.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable


LEGACY_COLUMNS = (
    "id", "date", "source", "category", "severity", "status", "detail", "resolution"
)
ID_RE = re.compile(r"^(?:IMP|APP)-(?:\d{4}|\d{8}-[0-9a-f]{6})$")
EMPTY_CELL = "—"

STAMP_HEAD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*驗證\s*")
VERDICT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
COST_RE = re.compile(r"成本\s*([SML](?:[–-][SML])?)")
FIX_SITE_RE = re.compile(r"`([^`]+)`")
FIX_SITE_HEAD_RE = re.compile(r"落點")
FIX_SITE_SHAPE_RE = re.compile(
    r"[/\\]|\.(py|sh|swift|yml|yaml|json|md|ts|js)\b|^\w[\w.-]*:\d"
)


def split_row_raw(line: str) -> list[str]:
    """Split a markdown row on unescaped pipes, preserving cell whitespace."""
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return parts


def clean(cell: str) -> str:
    return cell.strip().replace("\\|", "|")


def _anchors_ok(
    cells: list[str],
    *,
    categories: dict[str, Iterable[str]],
    severities: Iterable[str],
    parseable_statuses: Iterable[str],
) -> bool:
    if len(cells) < len(LEGACY_COLUMNS):
        return False
    known_categories = {category for values in categories.values() for category in values}
    return (
        cells[3] in known_categories
        and cells[4] in severities
        and cells[5] in parseable_statuses
    )


def _app_anchors_ok(
    cells: list[str],
    *,
    app_columns: tuple[str, ...],
    categories: dict[str, Iterable[str]],
    severities: Iterable[str],
    parseable_statuses: Iterable[str],
) -> bool:
    if len(cells) < len(app_columns):
        return False
    return (
        cells[4] in categories["APP"]
        and cells[5] in severities
        and cells[6] in parseable_statuses
    )


def parse_legacy_table(
    text: str,
    *,
    categories: dict[str, Iterable[str]],
    severities: Iterable[str],
    parseable_statuses: Iterable[str],
    app_columns: tuple[str, ...],
) -> tuple[list[dict], list[dict]]:
    """Parse the historical 8-column ledger and report malformed data rows."""
    rows: list[dict] = []
    problems: list[dict] = []
    severity_values = set(severities)
    status_values = set(parseable_statuses)

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        raw_cells = split_row_raw(line)
        if not raw_cells:
            continue
        cells = [clean(cell) for cell in raw_cells]
        looks_like_id = bool(ID_RE.match(cells[0]))

        if cells[0].startswith("APP-"):
            if not _app_anchors_ok(
                cells,
                app_columns=app_columns,
                categories=categories,
                severities=severity_values,
                parseable_statuses=status_values,
            ):
                problems.append({
                    "kind": "malformed-row",
                    "id": cells[0],
                    "line": lineno,
                    "columns": len(cells),
                    "expected": len(app_columns),
                })
            continue

        if not _anchors_ok(
            cells,
            categories=categories,
            severities=severity_values,
            parseable_statuses=status_values,
        ):
            if looks_like_id:
                problems.append({
                    "kind": "malformed-row",
                    "id": cells[0],
                    "line": lineno,
                    "columns": len(cells),
                    "expected": len(LEGACY_COLUMNS),
                })
            continue

        if not looks_like_id:
            problems.append({
                "kind": "unrecognised-id",
                "id": cells[0],
                "line": lineno,
                "note": "row has valid category/severity/status but its id is not an entry id",
            })
            continue

        if len(cells) > len(LEGACY_COLUMNS):
            problems.append({
                "kind": "malformed-row",
                "id": cells[0],
                "line": lineno,
                "columns": len(cells),
                "expected": len(LEGACY_COLUMNS),
                "note": "too many columns — two possible causes. (a) An "
                "unescaped `|` inside a cell: escape it as `\\|` and re-run; "
                "this is the historical hand-written case and it is fixable. "
                "(b) A 12-column generated view: `import` reads the LEGACY "
                "8-column table only, and the current view is deliberately NOT "
                "importable (IMP-20260805-355016 / -3df783) — its entries are "
                "one-file-per-entry under the store, read those instead.",
            })
            continue

        row = dict(zip(LEGACY_COLUMNS, cells))
        if row["resolution"] == EMPTY_CELL:
            row["resolution"] = ""
        rows.append(row)

    return rows, problems


def _single_or_miss(field: str, values: list[str], misses: list[dict]) -> str | None:
    unique = list(dict.fromkeys(values))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        misses.append({"field": field, "reason": f"{len(unique)} candidates, ambiguous",
                       "values": unique})
    return None


def extract_verdict_fields(
    resolution: str,
    *,
    verdicts: Iterable[str],
    duplicate_prefix: str,
) -> tuple[dict, list[dict]]:
    """Extract structured evidence from a resolution stamp without rewriting it."""
    fields: dict = {}
    misses: list[dict] = []
    text = resolution or ""
    head = STAMP_HEAD_RE.search(text)
    if not head:
        return fields, misses

    verdict_values = set(verdicts)
    token_match = VERDICT_TOKEN_RE.match(text, head.end())
    token = token_match.group(0).rstrip("-") if token_match else ""
    if token in verdict_values:
        fields["verdict"] = token
    elif token.startswith(duplicate_prefix):
        target = token[len(duplicate_prefix):]
        if ID_RE.match(target):
            fields["verdict"] = token
            fields["duplicate_of"] = target
        else:
            misses.append({"field": "verdict",
                           "reason": f"duplicate target is not an entry id: {target!r}"})
    else:
        misses.append({"field": "verdict",
                       "reason": f"unrecognised verdict token: {token!r}"})

    if "verdict" in fields:
        fields["verified_at"] = head.group(1)

    cost = _single_or_miss("cost", COST_RE.findall(text), misses)
    if cost:
        fields["cost"] = cost
    elif (
        "verdict" in fields
        and not str(fields["verdict"]).startswith(duplicate_prefix)
        and not any(miss["field"] == "cost" for miss in misses)
    ):
        misses.append({"field": "cost", "reason": "stamp states no cost this module can read"})

    fix_head = FIX_SITE_HEAD_RE.search(text)
    if fix_head:
        candidates = [
            candidate
            for candidate in FIX_SITE_RE.findall(text[fix_head.end():])
            if FIX_SITE_SHAPE_RE.search(candidate)
        ]
        site = _single_or_miss("fix_site", candidates, misses)
        if site:
            fields["fix_site"] = site
        elif not candidates:
            misses.append({
                "field": "fix_site",
                "reason": "落點 present but no backticked path-shaped token",
            })

    return fields, misses


def import_legacy(
    text: str,
    store: Path,
    *,
    parse_table: Callable[[str], tuple[list[dict], list[dict]]],
    extract_fields: Callable[[str], tuple[dict, list[dict]]],
    load_entry: Callable[[Path, str], dict],
    add_entry: Callable[..., dict],
    retired_statuses: dict[str, str],
    historical_id_digest: str,
) -> dict:
    """Import the legacy table into the active store, preserving extras."""
    rows, problems = parse_table(text)
    imported = 0
    for row in rows:
        if row.get("status") in retired_statuses:
            problems.append({"kind": "status-migrated", "id": row["id"],
                             "from": row["status"],
                             "to": retired_statuses[row["status"]]})
            row["status"] = retired_statuses[row["status"]]

        verdict_fields, misses = extract_fields(row["resolution"])
        for miss in misses:
            problems.append({"kind": "stamp-not-read", "id": row["id"], **miss})

        try:
            carried = load_entry(store, row["id"])
        except KeyError:
            carried = {}
        legacy_owned = set(LEGACY_COLUMNS) | {"schema", "stream"}
        carried_extra = {key: value for key, value in carried.items()
                         if key not in legacy_owned}

        try:
            entry = add_entry(
                store,
                overwrite=True,
                extra=carried_extra,
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
                historical=True,
                _gate=True,
            )
        except ValueError as exc:
            problems.append({"kind": "rejected-row", "id": row["id"], "error": str(exc)})
            continue
        if historical_id_digest in entry:
            problems.append({"kind": "historical-id-preserved", "id": entry["id"],
                             "derived_id": entry[historical_id_digest]})
        imported += 1

    return {"imported": imported, "problems": problems}
