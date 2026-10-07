#!/usr/bin/env -S uv run --python 3.13 python
"""tap_a11y_lint — gate `.onTapGesture` views that VoiceOver cannot see.

Bug class (issue #2053): `.onTapGesture` attaches a gesture recognizer but no
accessibility semantics. A colour swatch / pattern tile / list row built from
it announces as plain content — no button trait, no selected state — and gets
no 44pt hit target unless the author remembers one. The fix is on the
production side: use `Button` (trait + activation for free), or declare the
semantics next to the gesture.

Detection (single-file, structural):
  1. Anchor every `.onTapGesture` (with or without arguments / trailing
     closure) in comment/string-blanked source.
  2. Walk the modifier chain that follows the call (closure BODIES excluded,
     so a trait buried inside `.overlay { … }` cannot exempt the tap).
  3. Flag unless the chain declares one of:
       - `.accessibilityAddTraits(… isButton …)`
       - `.accessibilityAction(…)`
       - `.accessibilityHidden(true)` (decorative catcher, e.g. keyboard
         dismiss scrim)
     or an allow marker is present (see below).

Order matters: the declaration must come AFTER the gesture in the chain. A
trait placed on an enclosing container (e.g. a row-level `.accessibilityElement`
with `.isButton`) is not visible to a single-file chain walk — annotate the tap
with `// a11y-allow: <where the semantics live>` instead.

Out of scope (accepted false-negative surface): `.gesture(TapGesture())`,
`.simultaneousGesture`, `.onLongPressGesture`, and cross-file gesture wrappers.

Modes (mirrors ops/plain_deadzone_lint.py):
  --report          Print findings with file:line, exit 0. Local discovery.
  --baseline        Write the current normalized finding set to the baseline.
  --baseline-check  Set-difference vs baseline; exit 1 only on NEW findings.
  --strict          Any finding fails (exit 1).

Allowlist:
  - `// a11y-allow: <reason>` on the `.onTapGesture` line, on the comment line
    directly above it, or anywhere inside the call's source extent. Comment
    form only: a string literal containing the marker text cannot exempt.

Exclusions (file-level): **/Debug/**, *Preview*.swift, *Tests*.swift.

Baseline design — line-drift resistant. A finding's identity is
  `<relpath>::tap-a11y::<normalized-call-text>`, never its line number.

Env overrides (for tests): KG_TAP_A11Y_SRC, KG_TAP_A11Y_BASELINE.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

from _swift_scan import (
    blank_comments_and_strings,
    match_balanced,
    normalize,
    should_skip,
    skip_ws,
    walk_modifier_chain,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("KG_TAP_A11Y_SRC", ROOT / "ios" / "BooksAndVocab"))
BASELINE_FILE = Path(
    os.environ.get("KG_TAP_A11Y_BASELINE", ROOT / "ops" / "tap_a11y_baseline.txt")
)

TAP_RX = re.compile(r"\.onTapGesture\b")
# Evaluated on the semantic chain text only (strings/comments blanked, closure
# bodies excluded), so none of these can be satisfied by literal copy.
BUTTON_TRAIT_RX = re.compile(r"\.accessibilityAddTraits\([^)]*\bisButton\b")
ACTION_RX = re.compile(r"\.accessibilityAction\(")
HIDDEN_RX = re.compile(r"\.accessibilityHidden\(\s*true\s*\)")
ALLOW_RX = re.compile(r"//\s*a11y-allow:")
SNIPPET_MAX = 120


class Finding:
    __slots__ = ("rel", "lineno", "snippet")

    def __init__(self, rel: str, lineno: int, snippet: str):
        self.rel = rel
        self.lineno = lineno
        self.snippet = normalize(snippet)[:SNIPPET_MAX]

    def key(self) -> str:
        return f"{self.rel}::tap-a11y::{self.snippet}"

    def display(self) -> str:
        return (
            f"{self.rel}:{self.lineno}: [tap-a11y] {self.snippet}"
            "  → use Button, or add .accessibilityAddTraits(.isButton) after the "
            "gesture, or annotate // a11y-allow: <reason>"
        )


def _call_end(stripped: str, pos: int) -> int:
    """Index just past `.onTapGesture` plus its optional args and trailing closure."""
    n = len(stripped)
    i = TAP_RX.match(stripped, pos).end()  # type: ignore[union-attr]
    if i < n and stripped[i] == "(":
        i = match_balanced(stripped, i, "(", ")")
    j = skip_ws(stripped, i)
    if j < n and stripped[j] == "{":
        i = match_balanced(stripped, j, "{", "}")
    return i


def _has_allow(
    commented_lines: list[str], commented: str, start: int, end: int, lineno: int
) -> bool:
    if ALLOW_RX.search(commented, start, end):
        return True
    # The marker may trail the call's last line, past the chain end.
    last_lineno = commented.count("\n", 0, end) + 1
    for ln in range(lineno, last_lineno + 1):
        if ln <= len(commented_lines) and ALLOW_RX.search(commented_lines[ln - 1]):
            return True
    # ...or sit on the pure-comment line directly above.
    if lineno >= 2:
        above = commented_lines[lineno - 2].strip()
        if above.startswith("//") and ALLOW_RX.search(above):
            return True
    return False


def scan_file(path: Path, rel: str) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if "onTapGesture" not in text:
        return []
    stripped = blank_comments_and_strings(text)
    # Strings blanked, comments kept: the only text the allow-marker search
    # trusts — string copy spelling out `// a11y-allow:` cannot exempt.
    commented = blank_comments_and_strings(text, keep_comments=True)
    commented_lines = commented.splitlines()
    findings: list[Finding] = []
    for m in TAP_RX.finditer(stripped):
        call_end = _call_end(stripped, m.start())
        parts, chain_end = walk_modifier_chain(stripped, call_end)
        chain = " ".join(parts)
        if (
            BUTTON_TRAIT_RX.search(chain)
            or ACTION_RX.search(chain)
            or HIDDEN_RX.search(chain)
        ):
            continue
        lineno = stripped.count("\n", 0, m.start()) + 1
        if _has_allow(commented_lines, commented, m.start(), chain_end, lineno):
            continue
        findings.append(Finding(rel, lineno, text[m.start() : call_end]))
    return findings


def collect() -> list[Finding]:
    if not SRC.exists():
        print(f"ERROR: {SRC} not found", file=sys.stderr)
        sys.exit(2)
    files = [f for f in sorted(SRC.rglob("*.swift")) if not should_skip(f)]
    if not files:
        print(f"ERROR: {SRC} contains no scannable .swift files", file=sys.stderr)
        sys.exit(2)
    findings: list[Finding] = []
    for f in files:
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
            f"# tap_a11y_lint baseline — generated {dt.date.today().isoformat()}",
            "# Line-number-free finding keys: <relpath>::tap-a11y::<normalized-call-text>.",
            "# Regenerate after a sanctioned sweep:  bash ops/tap_a11y_lint.sh --baseline",
            "# Review-mode UI (TodayReview*, ReviewCardView) is baselined on purpose: epic #2036",
            "# decided VoiceOver is NOT a product requirement for review mode. Everything else",
            "# must use Button / declare a trait / carry // a11y-allow: — do not add keys here.",
            "",
        ]
        BASELINE_FILE.write_text("\n".join(header + keys) + "\n", encoding="utf-8")
        print(f"[tap_a11y_lint] wrote baseline: {len(keys)} findings → {BASELINE_FILE}")
        return 0

    if args.baseline_check:
        baseline = read_baseline()
        current = {f.key(): f for f in findings}
        new_keys = sorted(set(current) - baseline)
        if new_keys:
            print(
                f"[tap_a11y_lint] REGRESSION — {len(new_keys)} new finding(s):",
                file=sys.stderr,
            )
            for k in new_keys:
                print(f"  {current[k].display()}", file=sys.stderr)
            return 1
        print(
            f"[tap_a11y_lint] OK — {len(current)} finding(s), all within "
            f"baseline of {len(baseline)}."
        )
        return 0

    if args.strict:
        for f in findings:
            print(f.display(), file=sys.stderr)
        if findings:
            print(
                f"[tap_a11y_lint] FAIL — {len(findings)} finding(s). Use Button, add "
                ".accessibilityAddTraits(.isButton), or annotate // a11y-allow: <reason>.",
                file=sys.stderr,
            )
            return 1
        print("[tap_a11y_lint] OK — no findings.")
        return 0

    for f in findings:
        print(f.display())
    print(f"\n[tap_a11y_lint] total: {len(findings)} findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
