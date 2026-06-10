#!/usr/bin/env -S uv run --python 3.13 python
"""plain_deadzone_lint — gate `.plain` Button labels with transparent dead zones.

Bug class: `buttonStyle(.plain)` hit-testing falls through transparent pixels.
A Button whose label stretches past its visible content — `Spacer()` gaps or a
`.frame(maxWidth: .infinity)` — and has no `.contentShape(...)` is tappable
only on the drawn pixels: the middle of the row is dead (production bug caught
by the Settings UI flow, fixed in PR #904). Fix is always on the production
side: add `.contentShape(Rectangle())` to the label, never teach tests to aim
at the text.

Detection (single-file, structural):
  1. Anchor every `Button` expression; parse its argument list, its label
     closure (trailing closure of `Button(action:)/(role:action:)`, or the
     `label:` closure), and its modifier chain.
  2. Flag when the chain has `.buttonStyle(.plain)` / `PlainButtonStyle()`,
     the label region contains a transparency gap (`Spacer(` or
     `maxWidth: .infinity`), and neither label nor chain has `.contentShape(`.
  `Button("title") { action }` labels are solid text — never flagged.

Known out-of-scope (accepted false-negative surface, documented by review):
  - Gaps hidden inside cross-file label components (covered by the one-off
    audit; the lint is single-file by design).
  - Conditional styles (`.buttonStyle(flag ? PlainButtonStyle() : ...)`).
  - `#if` blocks interleaved in a modifier chain truncate the chain walk.
  - Non-literal titled inits (`Button(L10n.string(.x)) { action }`) treat the
    action closure as the label — harmless unless an action body contains a
    gap pattern.

Modes (mirrors ops/ui_token_lint.py):
  --report          Print findings with file:line, exit 0. Local discovery.
  --baseline        Write the current normalized finding set to the baseline.
  --baseline-check  Set-difference vs baseline; exit 1 only on NEW findings.
  --strict          Any finding fails (exit 1). CI gate.

Allowlist:
  - Inline: `// deadzone-allow: <reason>` on the `Button` line or anywhere
    within the button's source extent (custom hit overlay, intentional design).

Exclusions (file-level): **/Debug/**, *Preview*.swift, *Tests*.swift.

Baseline design — line-drift resistant. A finding's identity is
  `<relpath>::deadzone::<normalized-snippet>`, never its line number.

Env overrides (for tests): KG_DEADZONE_SRC, KG_DEADZONE_BASELINE.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("KG_DEADZONE_SRC", ROOT / "ios" / "BooksAndVocab"))
BASELINE_FILE = Path(
    os.environ.get("KG_DEADZONE_BASELINE", ROOT / "ops" / "plain_deadzone_baseline.txt")
)

SKIP_PATH_FRAGMENTS = ("/Debug/",)
SKIP_NAME_GLOBS = ("*Preview*.swift", "*Tests*.swift")

PLAIN_STYLE_RX = re.compile(
    r"\.buttonStyle\(\s*(?:\.plain\b|PlainButtonStyle\(\))"
)
GAP_RX = re.compile(r"\bSpacer\([^)]*\)?|maxWidth:\s*\.infinity")
CONTENT_SHAPE = ".contentShape("
# Comment-form only, so a string literal merely *containing* the marker text
# cannot exempt a real dead zone.
ALLOW_RX = re.compile(r"//\s*deadzone-allow:")
MULTI_TRAILING_RX = re.compile(r"\w+\s*:")

_WS = re.compile(r"\s+")


def normalize(snippet: str) -> str:
    return _WS.sub(" ", snippet.strip())


def should_skip(path: Path) -> bool:
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


class ButtonSite:
    __slots__ = ("start", "end", "args", "label", "chain")

    def __init__(self, start: int, end: int, args: str, label: str, chain: str):
        self.start = start
        self.end = end
        self.args = args
        self.label = label
        self.chain = chain


def parse_button(stripped: str, pos: int) -> ButtonSite | None:
    """Parse one `Button` expression anchored at `pos` in comment/string-blanked
    text. Returns None for shapes that carry no in-file label closure."""
    n = len(stripped)
    i = pos + len("Button")
    args = ""
    if i < n and stripped[i] == "(":
        end = match_balanced(stripped, i, "(", ")")
        args = stripped[i:end]
        i = end

    i = skip_ws(stripped, i)
    first_closure = ""
    if i < n and stripped[i] == "{":
        end = match_balanced(stripped, i, "{", "}")
        first_closure = stripped[i:end]
        i = end

    # `Button { action } label: { ... }` — the label: closure wins.
    j = skip_ws(stripped, i)
    label_closure = ""
    if stripped.startswith("label:", j):
        j = skip_ws(stripped, j + len("label:"))
        if j < n and stripped[j] == "{":
            end = match_balanced(stripped, j, "{", "}")
            label_closure = stripped[j:end]
            i = end

    if label_closure:
        label = label_closure
    elif first_closure:
        # Titled inits (`Button("x") { ... }`) make the trailing closure the
        # ACTION and the label solid text — skip. Everything else
        # (`Button(action:)`, `Button(role:action:)`, bare `Button { ... }`)
        # has the trailing closure as the label.
        titled = args.lstrip("( \t\n").startswith('"')
        if titled:
            return None
        label = first_closure
    else:
        return None  # no in-file label (e.g. `Button("x", action: f)`)

    # Modifier chain: `.name`, optional `(...)`, optional trailing `{...}`.
    # Only the `.name(...)` segments enter the semantic chain text — trailing
    # closure BODIES are walked past but excluded, so a `.contentShape` or
    # `.buttonStyle` buried inside `.overlay {…}` / `.alert {…} message: {…}`
    # can neither exempt nor plain-mark the button it doesn't apply to.
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
            # so the walk still sees a .buttonStyle further down the chain.
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
    chain = " ".join(chain_parts)
    return ButtonSite(pos, i, args, label, chain)


class Finding:
    __slots__ = ("rel", "lineno", "snippet")

    def __init__(self, rel: str, lineno: int, snippet: str):
        self.rel = rel
        self.lineno = lineno
        self.snippet = normalize(snippet)

    def key(self) -> str:
        return f"{self.rel}::deadzone::{self.snippet}"

    def display(self) -> str:
        return (
            f"{self.rel}:{self.lineno}: [deadzone] {self.snippet}"
            f"  → add .contentShape(Rectangle()) to the label"
        )


BUTTON_RX = re.compile(r"\bButton\b")


def scan_file(path: Path, rel: str) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if "buttonStyle" not in text:
        return []
    stripped = blank_comments_and_strings(text)
    # Strings blanked, comments kept: the only text the allow-marker search
    # trusts — string copy spelling out `// deadzone-allow:` cannot exempt.
    commented = blank_comments_and_strings(text, keep_comments=True)
    findings: list[Finding] = []
    for m in BUTTON_RX.finditer(stripped):
        site = parse_button(stripped, m.start())
        if site is None:
            continue
        if not PLAIN_STYLE_RX.search(site.chain):
            continue
        gap = GAP_RX.search(site.label)
        if not gap:
            continue
        if CONTENT_SHAPE in site.label or CONTENT_SHAPE in site.chain:
            continue
        if ALLOW_RX.search(commented, site.start, site.end):
            continue
        # The marker may also sit in a comment at the end of the Button's
        # first line, whose tail extends past site.start — check the full
        # line too.
        lineno = stripped.count("\n", 0, site.start) + 1
        commented_lines = commented.splitlines()
        if lineno <= len(commented_lines) and ALLOW_RX.search(commented_lines[lineno - 1]):
            continue
        lines = text.splitlines()
        style = PLAIN_STYLE_RX.search(site.chain)
        first_line = lines[lineno - 1].strip() if lineno <= len(lines) else "Button"
        snippet = f"{first_line} | gap: {gap.group(0)} | style: {style.group(0)})"
        findings.append(Finding(rel, lineno, snippet))
    return findings


def collect() -> list[Finding]:
    if not SRC.exists():
        print(f"ERROR: {SRC} not found", file=sys.stderr)
        sys.exit(2)
    findings: list[Finding] = []
    for f in sorted(SRC.rglob("*.swift")):
        if should_skip(f):
            continue
        findings.extend(scan_file(f, str(f.relative_to(SRC))))
    return findings


def read_baseline() -> set[str]:
    if not BASELINE_FILE.exists():
        return set()
    items: set[str] = set()
    for raw in BASELINE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.add(line)
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--report", action="store_true", default=True)
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--baseline-check", action="store_true")
    g.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    findings = collect()

    if args.baseline:
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        keys = sorted({f.key() for f in findings})
        header = [
            f"# plain_deadzone_lint baseline — generated {dt.date.today().isoformat()}",
            "# Line-number-free finding keys: <relpath>::deadzone::<normalized-snippet>.",
            "# Regenerate after a sanctioned sweep:  bash ops/plain_deadzone_lint.sh --baseline",
            "",
        ]
        BASELINE_FILE.write_text("\n".join(header + keys) + "\n", encoding="utf-8")
        print(f"[plain_deadzone_lint] wrote baseline: {len(keys)} findings → {BASELINE_FILE}")
        return 0

    if args.baseline_check:
        baseline = read_baseline()
        current = {f.key(): f for f in findings}
        new_keys = sorted(set(current) - baseline)
        if new_keys:
            print(
                f"[plain_deadzone_lint] REGRESSION — {len(new_keys)} new finding(s):",
                file=sys.stderr,
            )
            for k in new_keys:
                print(f"  {current[k].display()}", file=sys.stderr)
            return 1
        print(
            f"[plain_deadzone_lint] OK — {len(current)} finding(s), all within "
            f"baseline of {len(baseline)}."
        )
        return 0

    if args.strict:
        for f in findings:
            print(f.display(), file=sys.stderr)
        if findings:
            print(
                f"[plain_deadzone_lint] FAIL — {len(findings)} finding(s). Fix with "
                f".contentShape(Rectangle()) or annotate // deadzone-allow: <reason>.",
                file=sys.stderr,
            )
            return 1
        print("[plain_deadzone_lint] OK — no findings.")
        return 0

    for f in findings:
        print(f.display())
    print(f"\n[plain_deadzone_lint] total: {len(findings)} findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
