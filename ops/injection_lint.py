#!/usr/bin/env -S uv run --python 3.13 python
"""injection_lint — verify InjectionNext three-piece coverage on Views/.

Three rules:
  R1. Each non-private `struct X: View` (excluding Debug/Readium/PDFReader,
      and structs inside #Preview blocks) must be followed by
      `@ObserveInjection`.
  R2. Per-file arity: `@ObserveInjection` count == `.enableInjection()` count.
  R3. If a file contains `@ObserveInjection`, it must also `import Inject`.

Modes:
  --report          Print findings, exit 0.
  --baseline        Write current findings list to ops/injection_baseline.txt.
  --baseline-check  Compare current findings to baseline; fail if regressed.
  --strict          Any finding fails (exit 1).

The baseline file may contain a leading `# sunset: YYYY-MM-DD` line. After
that date `--baseline-check` warns even if findings haven't regressed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

VIEWS_ROOT = Path("ios/BooksAndVocab/Views")
BASELINE_FILE = Path(os.environ.get("KG_INJECTION_BASELINE", "ops/injection_baseline.txt"))
LOGGER = logging.getLogger(__name__)

# View-injection grammar shared with the codemod (single source of truth).
from _inject_shared import (  # noqa: E402
    SHIM,
    STRUCT_VIEW_RE,
    PREVIEW_OPEN_RE,
    inject_package_linked,
    should_skip_path,
)


def scan_file(path: Path) -> list[str]:
    """Return list of finding strings for this file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    findings: list[str] = []
    preview_depth = 0

    has_observe = "@ObserveInjection" in text
    has_import = "import Inject" in text

    # R3: the import must match what the project actually links (see
    # inject_package_linked). Either direction is a compile-time fact, not a
    # style preference.
    if inject_package_linked():
        if has_observe and not has_import:
            findings.append(f"{path}: missing `import Inject` despite @ObserveInjection usage")
    elif has_import:
        findings.append(
            f"{path}: `import Inject` does not compile — the Inject package is not linked; "
            f"@ObserveInjection comes from {SHIM}"
        )

    # R1: every qualifying View struct must be followed by @ObserveInjection
    for i, line in enumerate(lines):
        if preview_depth > 0:
            preview_depth += line.count("{") - line.count("}")
            if preview_depth <= 0:
                preview_depth = 0
            continue
        if PREVIEW_OPEN_RE.search(line):
            preview_depth = line.count("{") - line.count("}")
            if preview_depth < 0:
                preview_depth = 0
            continue

        m = STRUCT_VIEW_RE.match(line)
        if not m:
            continue
        access = m.group("access").strip()
        if access in ("private", "fileprivate"):
            continue
        protocol_list = [p.strip() for p in m.group("protocols").split(",")]
        if "View" not in protocol_list:
            continue
        name = m.group("name")
        # Look ahead for @ObserveInjection
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j >= len(lines) or "@ObserveInjection" not in lines[j]:
            findings.append(f"{path}:{i+1}: struct {name}: View missing @ObserveInjection")

    # R2: per-file arity
    obs_count = text.count("@ObserveInjection")
    enable_count = text.count(".enableInjection()")
    if obs_count != enable_count:
        findings.append(
            f"{path}: arity mismatch — @ObserveInjection={obs_count}, "
            f".enableInjection()={enable_count}"
        )

    return findings


def collect_findings() -> list[str]:
    if not VIEWS_ROOT.exists():
        print(f"ERROR: {VIEWS_ROOT} not found", file=sys.stderr)
        sys.exit(2)
    findings: list[str] = []
    for f in sorted(VIEWS_ROOT.rglob("*.swift")):
        if should_skip_path(f):
            continue
        findings.extend(scan_file(f))
    return findings


def read_baseline() -> tuple[set[str], dt.date | None]:
    if not BASELINE_FILE.exists():
        return set(), None
    sunset: dt.date | None = None
    items: set[str] = set()
    for raw in BASELINE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# sunset:"):
            try:
                sunset = dt.date.fromisoformat(line.split(":", 1)[1].strip())
            except ValueError:
                LOGGER.warning("Invalid sunset token in baseline: %r", raw.strip())
                print(f"[injection_lint] invalid sunset token in baseline: {raw.strip()}")
                sunset = None
            continue
        if line.startswith("#"):
            continue
        items.add(line)
    return items, sunset


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--report", action="store_true", default=True)
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--baseline-check", action="store_true")
    g.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    findings = collect_findings()

    if args.baseline:
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        today = dt.date.today()
        sunset = today + dt.timedelta(days=30)
        out_lines = [
            f"# injection_lint baseline — generated {today.isoformat()}",
            f"# sunset: {sunset.isoformat()}",
            "# After sunset, --baseline-check FAILS even when count hasn't regressed.",
            "",
            *findings,
        ]
        BASELINE_FILE.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"Wrote baseline: {len(findings)} findings → {BASELINE_FILE}")
        return 0

    if args.baseline_check:
        baseline_items, sunset = read_baseline()
        current = set(findings)
        new = sorted(current - baseline_items)
        if new:
            print(f"[injection_lint] REGRESSION — {len(new)} new findings:", file=sys.stderr)
            for n in new:
                print(f"  {n}", file=sys.stderr)
            return 1
        # A grace period that never expires is not a grace period. Until
        # 2026-08-03 an expired sunset printed a warning and still returned 0,
        # so the checked-in sunset sat 21 days past its date with every gate
        # green and nobody informed.
        if sunset is None:
            print(
                "[injection_lint] FAIL — baseline has no valid `# sunset: YYYY-MM-DD` "
                "header; debt without an expiry date is permanent by default. "
                "Regenerate with --baseline.",
                file=sys.stderr,
            )
            return 1
        if dt.date.today() > sunset:
            print(
                f"[injection_lint] FAIL — baseline sunset {sunset.isoformat()} has passed; "
                f"resolve the {len(baseline_items)} outstanding item(s), or make an explicit "
                f"dated decision to extend and regenerate with --baseline.",
                file=sys.stderr,
            )
            for item in sorted(baseline_items):
                print(f"  {item}", file=sys.stderr)
            return 1
        print(f"OK — {len(current)} findings (all within baseline of {len(baseline_items)}).")
        return 0

    if args.strict:
        for f in findings:
            print(f, file=sys.stderr)
        if findings:
            print(f"[injection_lint] FAIL — {len(findings)} findings", file=sys.stderr)
            return 1
        print("[injection_lint] OK — no findings.")
        return 0

    # Default: --report
    for f in findings:
        print(f)
    print(f"\nTotal: {len(findings)} findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
