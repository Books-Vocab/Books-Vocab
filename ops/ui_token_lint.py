#!/usr/bin/env -S uv run --python 3.13 python
"""ui_token_lint — gate raw spacing/radius/shadow/color/font magic numbers.

Every visual constant in the iOS app must flow through a design token:

  raw `.padding(<number>)`                  → AppSpacing.sN
  raw `.shadow(...)`                        → .appElevation(.zN)
  RoundedRectangle(cornerRadius: <number>)  → AppRadius.*
  `.cornerRadius(<number>)`                 → AppRadius.*
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

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("KG_UI_TOKEN_SRC", ROOT / "ios" / "BooksAndVocab"))
BASELINE_FILE = Path(
    os.environ.get("KG_UI_TOKEN_BASELINE", ROOT / "ops" / "ui_token_baseline.txt")
)

ALLOW_MARKER = "token-allow:"

# File-level exclusions. A path is skipped if any fragment matches, or its
# basename matches an exact-name exclusion, or it matches a glob.
SKIP_PATH_FRAGMENTS = ("/Debug/",)
SKIP_BASENAMES = ("AppMetrics.swift", "AppColors.swift")
SKIP_NAME_GLOBS = ("*Preview*.swift", "*Tests*.swift")

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
        "radius",
        re.compile(r"RoundedRectangle\(\s*cornerRadius:\s*-?\d|\.cornerRadius\(\s*-?\d"),
        "use AppRadius.*",
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

# Collapse runs of whitespace so the normalized key is indentation-invariant.
_WS = re.compile(r"\s+")


def normalize(snippet: str) -> str:
    return _WS.sub(" ", snippet.strip())


def should_skip(path: Path) -> bool:
    s = str(path)
    if any(frag in s for frag in SKIP_PATH_FRAGMENTS):
        return True
    if path.name in SKIP_BASENAMES:
        return True
    return any(path.match(g) for g in SKIP_NAME_GLOBS)


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
        return f"{self.rel}:{self.lineno}: [{self.pattern}] {self.snippet}  → {self.hint}"


def scan_file(path: Path, rel: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return findings
    for i, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue
        for pid, rx, hint in PATTERNS:
            if rx.search(line):
                findings.append(Finding(rel, i, pid, hint, line))
    return findings


def collect() -> list[Finding]:
    if not SRC.exists():
        print(f"ERROR: {SRC} not found", file=sys.stderr)
        sys.exit(2)
    files: list[Path] = []
    for f in sorted(SRC.rglob("*.swift")):
        if should_skip(f):
            continue
        files.append(f)
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
            f"# ui_token_lint baseline — generated {dt.date.today().isoformat()}",
            "# Line-number-free finding keys: <relpath>::<pattern>::<normalized-snippet>.",
            "# Regenerate after a sanctioned sweep:  bash ops/ui_token_lint.sh --baseline",
            "",
        ]
        BASELINE_FILE.write_text("\n".join(header + keys) + "\n", encoding="utf-8")
        print(f"[ui_token_lint] wrote baseline: {len(keys)} findings → {BASELINE_FILE}")
        return 0

    if args.baseline_check:
        baseline = read_baseline()
        current = {f.key(): f for f in findings}
        new_keys = sorted(set(current) - baseline)
        if new_keys:
            print(
                f"[ui_token_lint] REGRESSION — {len(new_keys)} new finding(s):",
                file=sys.stderr,
            )
            for k in new_keys:
                print(f"  {current[k].display()}", file=sys.stderr)
            return 1
        print(
            f"[ui_token_lint] OK — {len(current)} finding(s), all within "
            f"baseline of {len(baseline)}."
        )
        return 0

    if args.strict:
        for f in findings:
            print(f.display(), file=sys.stderr)
        if findings:
            print(
                f"[ui_token_lint] FAIL — {len(findings)} finding(s). Fix or "
                f"annotate with // token-allow: <reason>.",
                file=sys.stderr,
            )
            return 1
        print("[ui_token_lint] OK — no findings.")
        return 0

    # default --report
    for f in findings:
        print(f.display())
    print(f"\n[ui_token_lint] total: {len(findings)} findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
