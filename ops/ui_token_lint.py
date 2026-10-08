#!/usr/bin/env -S uv run --python 3.13 python
"""ui_token_lint — gate raw spacing/radius/shadow/color/font magic numbers.

Every visual constant in the iOS app must flow through a design token:

  raw `.padding(<number>)`                  → AppSpacing.sN
  raw `.shadow(...)`                        → .appElevation(.zN)
  RoundedRectangle(...) / Capsule(...)      → AppRoundedRect(roundness:)
  raw `cornerRadius: <number>`              → AppRoundness.* (dimensionless t)
  bare number in a `*[Rr]oundness:` arg     → AppRoundness.*
  raw hex color (Color(hex:/0xRRGGBB/#RGB)  → AppColors.*
  `.font(.system(size: <number>))`          → AppFonts.*

Modes (mirrors ops/injection_lint.py):
  --report          Print findings with file:line, exit 0. Local discovery.
  --baseline        Write the current normalized finding set to the baseline.
  --baseline-check  Set-difference vs baseline; exit 1 only on NEW findings.
  --strict          Any finding fails (exit 1). CI gate.

Allowlist:
  - Inline: `// token-allow: <reason>` on the same line exempts that line
    (brand color, intentional one-off hairline, etc.).

Exclusions (file-level): AppMetrics.swift (AppElevation/AppShadows impl),
  AppColors.swift (hex definition source), **/Debug/**, *Preview*.swift,
  *Tests*.swift.

Baseline design — line-drift resistant. A finding's identity is
  `<relpath>::<pattern>::<normalized-snippet>`, never its line number. A diff
  that only shifts line numbers (e.g. another track inserting code above) does
  NOT regress; only a NEW file / pattern / distinct snippet does. The baseline
  is a set; --baseline-check reports `current - baseline`.

Env overrides (for tests): KG_UI_TOKEN_SRC, KG_UI_TOKEN_BASELINE.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

from _swift_scan import collect_findings, normalize, run_modes

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("KG_UI_TOKEN_SRC", ROOT / "ios" / "BooksAndVocab"))
BASELINE_FILE = Path(
    os.environ.get("KG_UI_TOKEN_BASELINE", ROOT / "ops" / "ui_token_baseline.txt")
)

ALLOW_MARKER = "token-allow:"

# Extra file-level exclusions on top of _swift_scan.should_skip (Debug/, Preview, Tests).
SKIP_BASENAMES = ("AppMetrics.swift", "AppColors.swift")
LOGGER = logging.getLogger(__name__)

# (pattern_id, compiled regex, remediation hint). Order = report order.
PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        # Single-arg `.padding(12)` OR directional `.padding(.vertical, 13)`.
        # The directional branch requires the value arg to *begin* with a numeric
        # literal so token forms like `.padding(.vertical, AppSpacing.s3)` or
        # `.padding(.horizontal, skin.spacing.microGap)` are not flagged.
        "padding",
        re.compile(
            r"\.padding\(\s*-?\d+(?:\.\d+)?\s*\)"
            r"|\.padding\(\s*\.(?:vertical|horizontal|top|bottom|leading|trailing)\s*,"
            r"\s*-?\d+(?:\.\d+)?\s*\)"
        ),
        "use AppSpacing.sN",
    ),
    (
        "shadow",
        re.compile(r"\.shadow\("),
        "use .appElevation(.zN)",
    ),
    (
        # Absolute pt radii. The corner system is dimensionless now: radius is
        # derived from the shape's own box at render time.
        "radius",
        re.compile(
            r"RoundedRectangle\(\s*cornerRadius:\s*-?\d|\.cornerRadius\(\s*-?\d"
        ),
        "use AppRoundedRect(roundness: AppRoundness.*)",
    ),
    (
        # AppRoundedRect is the single entry point for rounded rectangles.
        # Reaching for the raw SwiftUI shapes bypasses the roundness plane, so
        # they need an explicit `// token-allow:` justification.
        "raw-rounded-shape",
        re.compile(r"\b(?:Uneven)?RoundedRectangle\(|\bCapsule\("),
        "use AppRoundedRect / AppUnevenRoundedRect",
    ),
    (
        # A bare number in the roundness plane means someone put a pt length
        # where a dimensionless t belongs — the exact confusion this system exists
        # to remove. `roundness: 0` and `roundness: 1` are the honest endpoints
        # and stay legal; anything else must name a token.
        # `\w*[Rr]oundness:` so the per-corner labels (`topRoundness:` /
        # `bottomRoundness:`) are covered too — a plain `roundness:` match is
        # case-sensitive and would sail straight past them.
        "roundness",
        re.compile(r"\w*[Rr]oundness:\s*(?!0\s*[),])(?!1\s*[),])-?\d"),
        "use AppRoundness.* (t is dimensionless, not pt)",
    ),
    (
        "color",
        re.compile(r"Color\(hex:|0x[0-9A-Fa-f]{6}(?![0-9A-Fa-f])|\"#[0-9A-Fa-f]{6}\""),
        "use AppColors.*",
    ),
    (
        "font",
        re.compile(r"\.font\(\.system\(size:"),
        "use AppFonts.*",
    ),
]


class Finding:
    __slots__ = ("rel", "lineno", "pattern", "hint", "snippet")

    def __init__(self, rel: str, lineno: int, pattern: str, hint: str, snippet: str):
        self.rel = rel
        self.lineno = lineno
        self.pattern = pattern
        self.hint = hint
        self.snippet = normalize(snippet)

    def key(self) -> str:
        """Line-number-free identity used for the baseline set."""
        return f"{self.rel}::{self.pattern}::{self.snippet}"

    def display(self) -> str:
        return (
            f"{self.rel}:{self.lineno}: [{self.pattern}] {self.snippet}  → {self.hint}"
        )


def _strip_comment(line: str) -> str:
    """Drop a trailing `//` comment so prose can name the very APIs the rules ban.

    Without this, any migration note or doc comment mentioning e.g.
    `RoundedRectangle` is flagged, which pressures authors into rewording
    accurate comments to appease the linter — the tool bending the work instead
    of the other way round.

    `//` inside a string literal is not a comment, so quotes are tracked. Swift
    string interpolation and multi-line strings are not modelled: this is a
    line-based linter and the rules only ever match code-shaped text, so the
    residual risk is a missed finding inside an interpolated segment, never a
    false positive.
    """
    in_string = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string and ch == "/" and line[idx + 1 : idx + 2] == "/":
            return line[:idx]
    return line


def scan_file(path: Path, rel: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        LOGGER.warning("scan failed for %s", path, exc_info=True)
        return findings
    for i, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue
        code = _strip_comment(line)
        if not code.strip():
            continue
        for pid, rx, hint in PATTERNS:
            if rx.search(code):
                findings.append(Finding(rel, i, pid, hint, line))
    return findings


def collect() -> list[Finding]:
    return collect_findings(SRC, scan_file, SKIP_BASENAMES)


def main() -> int:
    return run_modes(
        "ui_token_lint",
        collect(),
        BASELINE_FILE,
        [
            "# Line-number-free finding keys: <relpath>::<pattern>::<normalized-snippet>.",
            "# Regenerate after a sanctioned sweep:  bash ops/ui_token_lint.sh --baseline",
        ],
        "Fix or annotate with // token-allow: <reason>.",
    )


if __name__ == "__main__":
    sys.exit(main())
