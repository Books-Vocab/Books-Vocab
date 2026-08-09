#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Count selected Swift declarations without counting comments or strings."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Token:
    value: str
    line: int


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _skip_string(source: str, start: int, line: int) -> tuple[int, int]:
    """Return the first index after a Swift string and its ending line."""
    length = len(source)
    hashes = 0
    while start + hashes < length and source[start + hashes] == "#":
        hashes += 1
    quote = start + hashes
    if quote >= length or source[quote] != '"':
        return start + 1, line
    triple = source.startswith('"""', quote)
    opener = 3 if triple else 1
    close = '"' * opener + ('#' * hashes)
    i = quote + opener
    while i < length:
        if source.startswith(close, i):
            return i + len(close), line + source[i : i + len(close)].count("\n")
        if not hashes and not triple and source[i] == "\\":
            # Escaped quotes and escaped newlines are part of the string.
            i += 2
            continue
        if source[i] == "\n":
            line += 1
        i += 1
    return length, line


def tokenize(source: str) -> list[Token]:
    """Tokenize only the syntax needed by the two counters.

    Comments and strings are discarded as opaque regions. This intentionally
    also discards interpolation bodies: an annotation or `) async` written in
    a string must not become a declaration in the generated metric.
    """
    tokens: list[Token] = []
    i = 0
    line = 1
    length = len(source)
    while i < length:
        char = source[i]
        if char in " \t\r\f\v":
            i += 1
            continue
        if char == "\n":
            line += 1
            i += 1
            continue
        if source.startswith("//", i):
            newline = source.find("\n", i + 2)
            if newline == -1:
                break
            i = newline
            continue
        if source.startswith("/*", i):
            depth = 1
            i += 2
            while i < length and depth:
                if source.startswith("/*", i):
                    depth += 1
                    i += 2
                elif source.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    if source[i] == "\n":
                        line += 1
                    i += 1
            continue
        if char == '"' or (char == "#" and i + 1 < length and source[i + 1] == '"'):
            i, line = _skip_string(source, i, line)
            continue
        match = _IDENTIFIER.match(source, i)
        if match:
            tokens.append(Token(match.group(0), line))
            i = match.end()
            continue
        if source.startswith("->", i):
            tokens.append(Token("->", line))
            i += 2
            continue
        tokens.append(Token(char, line))
        i += 1
    return tokens


def count_async_functions(tokens: Iterable[Token]) -> int:
    tokens = list(tokens)
    total = 0
    for index, token in enumerate(tokens):
        if token.value != "func":
            continue
        open_index = next((j for j in range(index + 1, len(tokens)) if tokens[j].value == "("), None)
        if open_index is None:
            continue
        depth = 0
        close_index = None
        for j in range(open_index, len(tokens)):
            if tokens[j].value == "(":
                depth += 1
            elif tokens[j].value == ")":
                depth -= 1
                if depth == 0:
                    close_index = j
                    break
        if close_index is not None and close_index + 1 < len(tokens) and tokens[close_index + 1].value == "async":
            total += 1
    return total


def count_main_actor_lines(tokens: Iterable[Token]) -> int:
    tokens = list(tokens)
    return len({tokens[i].line for i in range(len(tokens) - 1) if tokens[i].value == "@" and tokens[i + 1].value == "MainActor"})


def swift_files(paths: Iterable[Path]) -> list[Path]:
    result: set[Path] = set()
    for path in paths:
        if path.is_dir():
            result.update(candidate for candidate in path.rglob("*.swift") if candidate.is_file())
        elif path.is_file() and path.suffix == ".swift":
            result.add(path)
    return sorted(result)


def count_kind(kind: str, paths: Iterable[Path]) -> int:
    total = 0
    for path in swift_files(paths):
        tokens = tokenize(path.read_text(encoding="utf-8"))
        if kind == "async-func":
            total += count_async_functions(tokens)
        else:
            total += count_main_actor_lines(tokens)
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("async-func", "main-actor"), required=True)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    print(count_kind(args.kind, args.paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
