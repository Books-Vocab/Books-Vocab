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

import os
import re
import sys
from pathlib import Path

from _swift_scan import (
    blank_comments_and_strings,
    collect_findings,
    match_balanced,
    normalize,
    run_modes,
    skip_ws,
    walk_modifier_chain,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("KG_DEADZONE_SRC", ROOT / "ios" / "BooksAndVocab"))
BASELINE_FILE = Path(
    os.environ.get("KG_DEADZONE_BASELINE", ROOT / "ops" / "plain_deadzone_baseline.txt")
)

PLAIN_STYLE_RX = re.compile(r"\.buttonStyle\(\s*(?:\.plain\b|PlainButtonStyle\(\))")
GAP_RX = re.compile(r"\bSpacer\([^)]*\)?|maxWidth:\s*\.infinity")
CONTENT_SHAPE = ".contentShape("
# Comment-form only, so a string literal merely *containing* the marker text
# cannot exempt a real dead zone.
ALLOW_RX = re.compile(r"//\s*deadzone-allow:")


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

    # Modifier chain: see _swift_scan.walk_modifier_chain (closure bodies excluded).
    chain_parts, i = walk_modifier_chain(stripped, i)
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
        if lineno <= len(commented_lines) and ALLOW_RX.search(
            commented_lines[lineno - 1]
        ):
            continue
        lines = text.splitlines()
        style = PLAIN_STYLE_RX.search(site.chain)
        first_line = lines[lineno - 1].strip() if lineno <= len(lines) else "Button"
        snippet = f"{first_line} | gap: {gap.group(0)} | style: {style.group(0)})"
        findings.append(Finding(rel, lineno, snippet))
    return findings


def collect() -> list[Finding]:
    return collect_findings(SRC, scan_file)


def main() -> int:
    return run_modes(
        "plain_deadzone_lint",
        collect(),
        BASELINE_FILE,
        [
            "# Line-number-free finding keys: <relpath>::deadzone::<normalized-snippet>.",
            "# Regenerate after a sanctioned sweep:  bash ops/plain_deadzone_lint.sh --baseline",
        ],
        "Fix with .contentShape(Rectangle()) or annotate // deadzone-allow: <reason>.",
    )


if __name__ == "__main__":
    sys.exit(main())
