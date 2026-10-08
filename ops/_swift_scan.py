"""Shared Swift source scanning primitives for the ops UI lints.

Comment/string blanking (newline-preserving), balanced-bracket matching and the
SwiftUI modifier-chain walker used by `plain_deadzone_lint.py` and
`tap_a11y_lint.py`, plus the file-collection, baseline and CLI-mode scaffolding
shared with `ui_token_lint.py`. Import-only module: no env, no import-time I/O.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

SKIP_PATH_FRAGMENTS = ("/Debug/",)
SKIP_NAME_GLOBS = ("*Preview*.swift", "*Tests*.swift")

_WS = re.compile(r"\s+")
MULTI_TRAILING_RX = re.compile(r"\w+\s*:")


def normalize(snippet: str) -> str:
    return _WS.sub(" ", snippet.strip())


def should_skip(path: Path, skip_basenames: tuple[str, ...] = ()) -> bool:
    """File-level exclusions shared by the UI lints: Debug/, *Preview*, *Tests*,
    plus any exact basenames the caller excludes."""
    s = str(path)
    if any(frag in s for frag in SKIP_PATH_FRAGMENTS):
        return True
    if path.name in skip_basenames:
        return True
    return any(path.match(g) for g in SKIP_NAME_GLOBS)


def collect_findings(
    src: Path,
    scan_file,
    skip_basenames: tuple[str, ...] = (),
    require_files: bool = False,
) -> list:
    """Scan every non-skipped `*.swift` under `src` with `scan_file(path, rel)`."""
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        sys.exit(2)
    files = [
        f for f in sorted(src.rglob("*.swift")) if not should_skip(f, skip_basenames)
    ]
    if require_files and not files:
        print(f"ERROR: {src} contains no scannable .swift files", file=sys.stderr)
        sys.exit(2)
    findings: list = []
    for f in files:
        findings.extend(scan_file(f, str(f.relative_to(src))))
    return findings


def read_baseline(baseline_file: Path) -> set[str]:
    if not baseline_file.exists():
        return set()
    items: set[str] = set()
    for raw in baseline_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.add(line)
    return items


def run_modes(
    tag: str,
    findings: list,
    baseline_file: Path,
    header_lines: list[str],
    fail_hint: str,
    description: str | None = None,
    blank_when_empty: bool = True,
) -> int:
    """Shared CLI: --report (default) / --baseline / --baseline-check / --strict.

    `findings` items expose key() and display(). `header_lines` are the baseline
    comment lines (sans the blank separator, added before the keys).
    """
    ap = argparse.ArgumentParser(description=description)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--report", action="store_true", default=True)
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--baseline-check", action="store_true")
    g.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    if args.baseline:
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        keys = sorted({f.key() for f in findings})
        stamp = f"# {tag} baseline — generated {dt.date.today().isoformat()}"
        body = [stamp, *header_lines] + (
            [""] + keys if keys or blank_when_empty else []
        )
        baseline_file.write_text("\n".join(body) + "\n", encoding="utf-8")
        print(f"[{tag}] wrote baseline: {len(keys)} findings → {baseline_file}")
        return 0

    if args.baseline_check:
        baseline = read_baseline(baseline_file)
        current = {f.key(): f for f in findings}
        new_keys = sorted(set(current) - baseline)
        if new_keys:
            print(
                f"[{tag}] REGRESSION — {len(new_keys)} new finding(s):", file=sys.stderr
            )
            for k in new_keys:
                print(f"  {current[k].display()}", file=sys.stderr)
            return 1
        print(
            f"[{tag}] OK — {len(current)} finding(s), all within "
            f"baseline of {len(baseline)}."
        )
        return 0

    if args.strict:
        for f in findings:
            print(f.display(), file=sys.stderr)
        if findings:
            print(
                f"[{tag}] FAIL — {len(findings)} finding(s). {fail_hint}",
                file=sys.stderr,
            )
            return 1
        print(f"[{tag}] OK — no findings.")
        return 0

    for f in findings:
        print(f.display())
    print(f"\n[{tag}] total: {len(findings)} findings", file=sys.stderr)
    return 0


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
