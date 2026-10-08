#!/usr/bin/env -S uv run --python 3.13 python
# Report keys defined more than once inside one .strings / .stringsdict file.
#
# CFPropertyList (plutil, NSBundle) accepts a repeated key and keeps the LAST value,
# so the earlier definition is dead and its call sites get the other meaning. Keys
# are scoped per file (per <dict> in a .stringsdict); another locale is fine.
# Usage: _i18n_duplicate_keys.py <root>. Exits 0; an unparseable file and a root
# without any .strings file are findings too, so the gate fails closed.

from __future__ import annotations

import itertools
import re
import sys
import xml.parsers.expat
from pathlib import Path

TOKEN = re.compile(
    r'\s+|//[^\n]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"|[=;]|[^\s=;"/]+', re.DOTALL
)


def strings_entries(text: str):
    """Yield (key, value, line, scope) per `key = value;`; ValueError(line, why)."""
    tokens, pos, line = [], 0, 1
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise ValueError(line, f"unexpected {text[pos]!r}")
        if not m[0].isspace() and not m[0].startswith(("//", "/*")):
            tokens.append((m[0], line))
        line, pos = line + m[0].count("\n"), m.end()
    for i in range(0, len(tokens), 4):
        entry = tokens[i : i + 4]
        shape = "".join(t if t in ("=", ";") else "s" for t, _ in entry)
        if shape != "s=s;":
            bad = next((j for j, c in enumerate(shape) if c != "s=s;"[j]), -1)
            tok, at = entry[bad]
            raise ValueError(at, f"expected `key = value;` near {tok!r}")
        key, value = (t[1:-1] if t.startswith('"') else t for t, _ in entry[0:3:2])
        yield key, value, entry[0][1], 0


def stringsdict_entries(data: bytes):
    """Return (key, None, line, scope) per <key>; scope = its enclosing <dict>."""
    parser, ids = xml.parsers.expat.ParserCreate(), itertools.count()
    stack, found, buf = [], [], []

    def start(name, _attrs):
        if name == "dict":
            stack.append(next(ids))
        buf.clear()

    def end(name):
        if name == "key":
            found.append(("".join(buf), None, parser.CurrentLineNumber, stack[-1]))
        elif name == "dict":
            stack.pop()

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.CharacterDataHandler = buf.append
    try:
        parser.Parse(data, True)
    except xml.parsers.expat.ExpatError as exc:
        raise ValueError(exc.lineno, str(exc)) from exc
    return found


def main(root: Path) -> None:
    files = sorted(root.rglob("*.strings")) + sorted(root.rglob("*.stringsdict"))
    if not any(f.suffix == ".strings" for f in files):
        print(f"no .strings files under {root}")
    for path in files:
        if path.is_relative_to(Path.cwd()):
            path = path.relative_to(Path.cwd())
        try:
            if path.suffix == ".strings":
                entries = list(strings_entries(path.read_text("utf-8-sig")))
            else:
                entries = stringsdict_entries(path.read_bytes())
        except UnicodeDecodeError as exc:  # before ValueError: it is a subclass
            print(f"{path}:0: unparseable: not UTF-8 ({exc.reason})")
            continue
        except ValueError as exc:
            print(f"{path}:{exc.args[0]}: unparseable: {exc.args[1]}")
            continue
        first: dict[tuple, tuple] = {}
        for key, value, line, scope in entries:
            if (scope, key) not in first:
                first[(scope, key)] = (line, value)
                continue
            was_line, was = first[(scope, key)]
            change = f': "{was}" -> "{value}"' if value is not None else ""
            first_at = f"{path}:{was_line}"
            print(f'{path}:{line}: duplicate key "{key}", first at {first_at}{change}')


if __name__ == "__main__":
    main(Path(sys.argv[1]))
