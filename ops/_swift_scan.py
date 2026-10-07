"""Shared Swift source scanning primitives for the ops UI lints.

Comment/string blanking (newline-preserving), balanced-bracket matching and the
SwiftUI modifier-chain walker used by `plain_deadzone_lint.py` and
`tap_a11y_lint.py`. Import-only module: no CLI, no I/O, no env.
"""

from __future__ import annotations

import re
from pathlib import Path

SKIP_PATH_FRAGMENTS = ("/Debug/",)
SKIP_NAME_GLOBS = ("*Preview*.swift", "*Tests*.swift")

_WS = re.compile(r"\s+")
MULTI_TRAILING_RX = re.compile(r"\w+\s*:")


def normalize(snippet: str) -> str:
    return _WS.sub(" ", snippet.strip())


def should_skip(path: Path) -> bool:
    """File-level exclusions shared by the UI lints: Debug/, *Preview*, *Tests*."""
    s = str(path)
    if any(frag in s for frag in SKIP_PATH_FRAGMENTS):
        return True
    return any(path.match(g) for g in SKIP_NAME_GLOBS)


def blank_comments_and_strings(text: str, keep_comments: bool = False) -> str:
    """Replace comment bodies and string-literal contents with spaces.

    Keeps every newline (so line numbers survive) and keeps the quote
    characters themselves (so a titled `Button("x")` is still recognizable by
    its leading `"`). Handles `//`, nested `/* */`, `"` with `\\` escapes,
    `\"\"\"` multiline strings, and `\\(...)` interpolation (blanked with the
    rest of the string so stray braces inside can't break brace matching).

    With `keep_comments=True` only strings are blanked (comments are skipped
    over but left intact) — that variant is what the allow-marker search runs
    on, so a marker is honored only in a real comment, never in string copy.
    """
    out = list(text)
    i, n = 0, len(text)

    def blank(a: int, b: int) -> None:
        for j in range(a, b):
            if out[j] != "\n":
                out[j] = " "

    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            if not keep_comments:
                blank(i, j)
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth += 1
                    j += 2
                elif text.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if not keep_comments:
                blank(i, j)
            i = j
        elif c == '"':
            triple = text.startswith('"""', i)
            quote_len = 3 if triple else 1
            j = i + quote_len
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if triple and text.startswith('"""', j):
                    j += 3
                    break
                if not triple and (text[j] == '"' or text[j] == "\n"):
                    j += 1
                    break
                j += 1
            blank(i + quote_len, max(i + quote_len, j - quote_len))
            i = j
        else:
            i += 1
    return "".join(out)


def match_balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """`text[start]` must be `open_ch`; return index just past its match."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] in " \t\n\r":
        i += 1
    return i


CHAIN_STEP_RX = re.compile(r"\.\w+")


def walk_modifier_chain(stripped: str, i: int) -> tuple[list[str], int]:
    """Walk the modifier chain starting at `i` in comment/string-blanked text.

    Steps are `.name`, optional `(...)`, optional trailing `{...}`. Only the
    `.name(...)` segments enter the returned semantic parts — trailing closure
    BODIES are walked past but excluded, so a modifier buried inside
    `.overlay {...}` / `.alert {...} message: {...}` can neither exempt nor
    mark the view it does not apply to. Returns (parts, index just past the
    chain).
    """
    n = len(stripped)
    chain_parts: list[str] = []
    while True:
        j = skip_ws(stripped, i)
        m = CHAIN_STEP_RX.match(stripped, j)
        if not m:
            break
        seg_start = j
        j = m.end()
        if j < n and stripped[j] == "(":
            j = match_balanced(stripped, j, "(", ")")
        chain_parts.append(stripped[seg_start:j])
        k = skip_ws(stripped, j)
        if k < n and stripped[k] == "{":
            j = match_balanced(stripped, k, "{", "}")
            # Multi-trailing-closure modifiers (`.alert("t", isPresented:) {…}
            # message: {…}`) continue with `name: {…}` segments; consume them
            # so the walk still sees modifiers further down the chain.
            while True:
                k = skip_ws(stripped, j)
                m2 = MULTI_TRAILING_RX.match(stripped, k)
                if not m2:
                    break
                k2 = skip_ws(stripped, m2.end())
                if k2 < n and stripped[k2] == "{":
                    j = match_balanced(stripped, k2, "{", "}")
                else:
                    break
        i = j
    return chain_parts, i
