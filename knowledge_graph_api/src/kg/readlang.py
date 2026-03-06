"""Readlang TSV importer — converts Readlang export to KG Cards."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any


# Known Readlang column names (case-insensitive matching)
_ALIASES: dict[str, str] = {
    "original": "content",
    "word": "content",
    "translation": "meaning",
    "context": "example",
    "context (with translation)": "example",
    "context (with original word)": "example",
    "source": "source",
}


def _normalise_header(raw: str) -> str:
    """Map a Readlang header to our internal key."""
    return _ALIASES.get(raw.strip().lower(), raw.strip().lower())


def _convert_context(context: str, word: str) -> str:
    """Convert Readlang context to KG example format.

    Readlang uses [[translation]] or just has the word in context.
    We want to produce: 'The lawyer **invoked** the law.'
    """
    # Remove [[...]] translation markers (Readlang format)
    # e.g. "Reds became [[栗色]]." → "Reds became 栗色."
    cleaned = re.sub(r"\[\[(.+?)\]\]", r"\1", context)

    # Try to bold the original word in the context
    # Use case-insensitive word boundary match
    if word:
        # Escape regex special chars in word
        escaped = re.escape(word)
        # Match the word (possibly with different case or inflection)
        # Simple approach: find exact match first
        pattern = re.compile(rf"(?i)\b({escaped})\b")
        if pattern.search(cleaned):
            cleaned = pattern.sub(r"**\1**", cleaned, count=1)
        else:
            # Fallback: try to find the word stem (first 4+ chars)
            stem = word[:4] if len(word) > 4 else word
            stem_pattern = re.compile(rf"(?i)\b({re.escape(stem)}\w*)\b")
            match = stem_pattern.search(cleaned)
            if match:
                cleaned = cleaned[:match.start()] + f"**{match.group(1)}**" + cleaned[match.end():]

    return cleaned.strip()


def parse_readlang_tsv(path: Path) -> list[dict[str, Any]]:
    """Parse a Readlang-exported TSV/TXT file into a list of card dicts.

    Supports:
    - Tab-separated or semicolon-separated
    - With or without header row
    - Auto-detection of delimiter

    Returns list of dicts with keys: content, meaning, examples, source
    """
    text = path.read_text(encoding="utf-8-sig")
    lines = [l for l in text.strip().splitlines() if l.strip()]

    if not lines:
        return []

    # Detect delimiter
    first_line = lines[0]
    if "\t" in first_line:
        delimiter = "\t"
    elif ";" in first_line:
        delimiter = ";"
    else:
        delimiter = "\t"  # default

    # Check if first line is a header
    fields = first_line.split(delimiter)
    normalised = [_normalise_header(f) for f in fields]

    has_header = any(k in ("content", "meaning", "example", "source") for k in normalised)

    if has_header:
        headers = normalised
        data_lines = lines[1:]
    else:
        # No header — auto-detect column order using [[...]] markers
        # Readlang context columns contain [[word]] markers
        n_cols = len(fields)
        
        if n_cols >= 3:
            # Check which column has [[...]] (that's the context/example column)
            has_brackets = [bool(re.search(r"\[\[.+?\]\]", f)) for f in fields]
            if has_brackets[2]:
                # word, translation, context (most common with our recommended export)
                headers = ["content", "meaning", "example"]
            elif has_brackets[0]:
                # context, word (Readlang default when only 2 selected but 3 cols)
                headers = ["example", "content", "meaning"]
            else:
                # Fallback: assume word, translation, context
                headers = ["content", "meaning", "example"]
        elif n_cols == 2:
            has_brackets = [bool(re.search(r"\[\[.+?\]\]", f)) for f in fields]
            if has_brackets[0]:
                headers = ["example", "content"]
            else:
                headers = ["content", "meaning"]
        else:
            headers = ["content"]
        data_lines = lines

    results: list[dict[str, Any]] = []

    for line in data_lines:
        cols = line.split(delimiter)

        row: dict[str, Any] = {}
        for i, val in enumerate(cols):
            if i < len(headers):
                key = headers[i]
                row[key] = val.strip()

        # Must have at least content
        content = row.get("content", "").strip()
        if not content:
            continue

        meaning = row.get("meaning", "").strip()
        example_raw = row.get("example", "").strip()

        card: dict[str, Any] = {
            "content": content,
            "meaning": meaning or "",
            "pos": None,
            "examples": [],
            "collocations": [],
            "mode": "recognition",
        }

        # Convert context to example
        if example_raw:
            example = _convert_context(example_raw, content)
            card["examples"] = [example]

        # Keep source as metadata (optional)
        if row.get("source"):
            card["source"] = row["source"]

        results.append(card)

    return results
