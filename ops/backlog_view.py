"""Deterministic rendering helpers for the backlog's human-readable view."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from backlog_legacy import EMPTY_CELL, ID_RE, LEGACY_COLUMNS


VIEW_IMP_COLUMNS = (
    *LEGACY_COLUMNS, "verdict", "verified_at", "cost", "fix_site",
)
APP_COLUMNS = (
    "id", "date", "source", "surface", "category", "severity", "status",
    "detail", "repro", "build", "resolution",
)
def cell(value: str) -> str:
    """Make a value safe to sit inside a markdown table cell."""
    text = str(value or "")
    text = text.replace("\n", " ").replace("\r", " ")
    return text.replace("|", "\\|")


def render_table(entries: list[dict], columns: tuple[str, ...]) -> str:
    head = "| " + " | ".join(columns) + " |\n"
    sep = "|" + "|".join("---" for _ in columns) + "|\n"
    body = ""
    for entry in entries:
        cells = [cell(entry.get(column, "")) or EMPTY_CELL for column in columns]
        body += "| " + " | ".join(cells) + " |\n"
    return head + sep + body


def _split_row_raw(line: str) -> list[str]:
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return parts


def _clean(cell_value: str) -> str:
    return cell_value.strip().replace("\\|", "|")


def view_entry_ids(
    text: str,
    *,
    split_row_raw_fn: Callable[[str], list[str]] = _split_row_raw,
    clean_fn: Callable[[str], str] = _clean,
    id_re: re.Pattern[str] = ID_RE,
) -> set[str]:
    """Return ids in the first cell of both IMP and APP rendered tables."""
    ids: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = split_row_raw_fn(line)
        if cells:
            first = clean_fn(cells[0])
            if id_re.match(first):
                ids.add(first)
    return ids


def render_view(
    store: Path,
    *,
    verified_against: str,
    list_entries: Callable[..., list[dict]],
    view_header: str,
    imp_intro: str,
    app_intro: str,
    categories: dict[str, tuple[str, ...]],
    statuses: tuple[str, ...],
    severities: tuple[str, ...],
    verdicts: tuple[str, ...],
) -> str:
    """Render the human-readable view of the store deterministically."""
    imp = list_entries(store, stream="IMP")
    app = list_entries(store, stream="APP")
    out = view_header.format(
        verified_against=verified_against,
        imp_categories=" / ".join(f"`{category}`" for category in categories["IMP"]),
        app_categories=" / ".join(f"`{category}`" for category in categories["APP"]),
        statuses=" → ".join(f"`{status}`" for status in statuses),
        severities=" / ".join(f"`{severity}`" for severity in severities),
        verdicts=" / ".join(f"`{verdict}`" for verdict in verdicts),
    )
    out += imp_intro + "\n" + render_table(imp, VIEW_IMP_COLUMNS)
    out += app_intro + "\n" + render_table(app, APP_COLUMNS)
    return out


def view_counts(
    store: Path,
    *,
    list_entries: Callable[..., list[dict]],
) -> dict[str, int]:
    """Return view counts without persisting aggregate footer lines."""
    imp = list_entries(store, stream="IMP")
    app = list_entries(store, stream="APP")
    unresolved = [entry for entry in imp + app
                  if entry.get("status") not in ("fixed", "wont-fix")]
    return {
        "imp": len(imp),
        "app": len(app),
        "unresolved": len(unresolved),
        "groomed": sum(1 for entry in unresolved if entry.get("groomed_by")),
    }
