#!/usr/bin/env -S uv run --script
"""Validate executable references advertised by the agent constitution."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_LAW_RE = re.compile(
    r"^\s*\d+\.\s+\*\*[^*]+\*\*\s+`\[(machine|prompt|text-only)\]`"
)
_LAW_HEADING_RE = re.compile(r"^\s*\d+\.\s+\*\*[^*]+\*\*")
_PRIMARY_MARKER_RE = re.compile(
    r"^\s*\d+\.\s+\*\*[^*]+\*\*\s+`\[(machine|prompt|text-only)\]`"
)
_REFERENCE_RE = re.compile(
    r"(?<![\w./-])"
    r"(?P<token>(?:ops/|docs/)[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"
    r"(?::[A-Za-z_][A-Za-z0-9_]*)?"
    r"|[A-Za-z0-9_.-]+\.py:[A-Za-z_][A-Za-z0-9_]*)"
    r"(?![\w./-])"
)


def _normalise_path(token: str) -> tuple[str, str | None]:
    path, separator, symbol = token.partition(":")
    if path == "worktree_orchestrate.py":
        path = "ops/worktree_orchestrate.py"
    return path, symbol if separator else None


def _law_lines(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("## 鐵律"))
    except StopIteration:
        return []
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return [
        (line_no, line)
        for line_no, line in enumerate(lines[start:end], start + 1)
        if _LAW_HEADING_RE.match(line)
    ]


def machine_references(text: str) -> list[tuple[int, str, str, str | None]]:
    """Return ``(line_no, raw_token, path, symbol)`` for machine-law refs."""
    references: list[tuple[int, str, str, str | None]] = []
    for line_no, line in _law_lines(text):
        if not (_LAW_RE.match(line) and "[machine]" in line):
            continue
        for match in _REFERENCE_RE.finditer(line):
            raw = match.group("token")
            path, symbol = _normalise_path(raw)
            references.append((line_no, raw, path, symbol))
    return references


def validate_constitution(path: Path) -> list[str]:
    """Validate every file/symbol reference in every machine law in ``path``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: unable to read constitution: {exc}"]

    errors: list[str] = []
    root = path.parent
    law_lines = _law_lines(text)
    if len(law_lines) != 9:
        errors.append(f"{path}: expected exactly 9 iron laws, found {len(law_lines)}")
    for line_no, line in law_lines:
        marker_count = 1 if _PRIMARY_MARKER_RE.match(line) else 0
        if marker_count != 1:
            errors.append(
                f"{path}:{line_no}: expected exactly one primary enforcement marker, "
                f"found {marker_count}"
            )
    for line_no, raw, relative, symbol in machine_references(text):
        target = root / relative
        if not target.is_file():
            errors.append(f"{path}:{line_no}: {raw}: missing file {relative}")
            continue
        if symbol and symbol not in target.read_text(encoding="utf-8"):
            errors.append(f"{path}:{line_no}: {raw}: missing symbol {symbol} in {relative}")
    return errors


def main(argv: list[str] | None = None) -> int:
    paths = [Path(value) for value in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        print("usage: constitution_lint.py CONSTITUTION...", file=sys.stderr)
        return 64
    errors = [error for path in paths for error in validate_constitution(path)]
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
