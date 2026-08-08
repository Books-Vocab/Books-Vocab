#!/usr/bin/env -S uv run --python 3.13 python
"""injection_lint — verify InjectionNext three-piece coverage on Views/.

Three rules:
  R1. Each non-private `struct X: View` (excluding Debug/Readium/PDFReader,
      and structs inside #Preview blocks) must be followed by
      `@ObserveInjection`.
  R2. Per-file arity: `@ObserveInjection` count == `.enableInjection()` count.
  R3. If a file contains `@ObserveInjection`, it must also `import Inject`.

Modes:
  --report          Print findings; exit 0 for any tree it can scan.
  --baseline        Write current findings list to ops/injection_baseline.txt.
  --baseline-check  Compare current findings to baseline; fail if regressed.
  --strict          Any finding fails (exit 1).

Exit 2 (all modes) is a structural failure, not a verdict: the Views tree is
missing, or the scan examined zero files. Those are never reported as clean.

Paths are anchored to the repo, not to the caller's cwd — the Views tree and
`KG_INJECTION_BASELINE` resolve the same from any directory (relative overrides
against the repo root, exactly as ops/ui_quality_gate.py resolves them before
spawning this tool). Findings still name files repo-relatively, so the baseline
stays portable.

The baseline file may contain a leading `# sunset: YYYY-MM-DD` line. After
that date `--baseline-check` warns even if findings haven't regressed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import sys
from pathlib import Path

# Everything this tool addresses is anchored to the repo, never to the caller's
# cwd. Both constants below used to be bare relative Paths, which made the whole
# verdict a function of where the invoker happened to stand: from ops/ the scan
# found no Views tree at all, and from a directory holding a laxer
# ops/injection_baseline.txt the gate would have read *that* one and forgiven
# everything. ops/backlog.py carried the identical line and was ROOT-anchored on
# 2026-08-07 after the second shape was measured there; ops/inject_codemod.py:27
# (which shares this tool's grammar) had ROOT-anchoring right all along — but only
# that: it still feeds absolute paths to should_skip_path and still reports a
# zero-file run as success (IMP-20260808-e03c92).
ROOT = Path(__file__).resolve().parents[1]
VIEWS_ROOT = ROOT / "ios/BooksAndVocab/Views"

# Resolved character-for-character like ops/ui_quality_gate.py:injection_args —
# same variable, same default, absolute-vs-relative decided the same way. The
# parent plans --baseline-check from its answer and the child enforces against
# its own; the only way two processes cannot disagree about a path is to resolve
# it identically, default included. Note `KG_INJECTION_BASELINE=` (empty) still
# resolves to the repo root, i.e. a directory: that is the shape the parent
# deliberately rejects with .is_file() before ever spawning us (IMP-0048), and
# "fixing" it here would re-open the split.
_BASELINE_RAW = os.environ.get("KG_INJECTION_BASELINE", "ops/injection_baseline.txt")
_BASELINE_CANDIDATE = Path(_BASELINE_RAW)
BASELINE_FILE = (
    _BASELINE_CANDIDATE if _BASELINE_CANDIDATE.is_absolute() else ROOT / _BASELINE_CANDIDATE
)
LOGGER = logging.getLogger(__name__)

# View-injection grammar shared with the codemod (single source of truth).
from _inject_shared import (  # noqa: E402
    SHIM,
    SKIP_PATH_FRAGMENTS,
    STRUCT_VIEW_RE,
    PREVIEW_OPEN_RE,
    inject_package_linked,
    should_skip_path,
)


def _display(path: Path) -> str:
    """How a file is named inside a finding string: repo-relative.

    VIEWS_ROOT is absolute so the scan cannot follow the caller's cwd, but the
    finding strings are diffed against ops/injection_baseline.txt and written
    back into it by --baseline. Absolute paths there would bake one machine's
    home directory into a version-controlled file and make every entry read as
    NEW on any other checkout. The fallback covers roots outside the repo (the
    regression tests point VIEWS_ROOT at a temp tree).
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def scan_file(path: Path) -> list[str]:
    """Return list of finding strings for this file."""
    label = _display(path)
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
            findings.append(f"{label}: missing `import Inject` despite @ObserveInjection usage")
    elif has_import:
        findings.append(
            f"{label}: `import Inject` does not compile — the Inject package is not linked; "
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
            findings.append(f"{label}:{i+1}: struct {name}: View missing @ObserveInjection")

    # R2: per-file arity
    obs_count = text.count("@ObserveInjection")
    enable_count = text.count(".enableInjection()")
    if obs_count != enable_count:
        findings.append(
            f"{label}: arity mismatch — @ObserveInjection={obs_count}, "
            f".enableInjection()={enable_count}"
        )

    return findings


def collect_findings() -> list[str]:
    if not VIEWS_ROOT.exists():
        print(f"ERROR: {VIEWS_ROOT} not found", file=sys.stderr)
        sys.exit(2)
    candidates = sorted(VIEWS_ROOT.rglob("*.swift"))
    findings: list[str] = []
    scanned = 0
    for f in candidates:
        # Decide the skip on the path *inside* the tree. should_skip_path is a
        # substring match and VIEWS_ROOT is now absolute, so a checkout that
        # happened to live under a directory named Debug/ or Readium would
        # otherwise exclude every file and hand back a clean-looking scan.
        if should_skip_path(f.relative_to(VIEWS_ROOT)):
            continue
        scanned += 1
        findings.extend(scan_file(f))

    # An empty findings list means one of two very different things: "every file
    # is compliant" or "no file was read". Only the first is a pass. Until
    # 2026-08-08 both printed `OK — no findings.` and exited 0, which is the
    # other half of the cwd defect above — pointed at the wrong tree, this lint
    # certified it. Same doctrine as ops/ui_fixture_lint.sh's exit 2: a lint
    # that cannot see anything is the kind that stays silent forever.
    if scanned == 0:
        why = (
            "no .swift file exists under it"
            if not candidates
            else f"all {len(candidates)} .swift file(s) under it are excluded by "
            f"{list(SKIP_PATH_FRAGMENTS)}"
        )
        print(
            f"ERROR: scanned 0 files under {VIEWS_ROOT} — {why}. A lint that examined "
            f"nothing has not shown that anything is clean; refusing to report an empty "
            f"findings list as a pass.",
            file=sys.stderr,
        )
        sys.exit(2)
    return findings


_LINE_KEYED = re.compile(r"^(?P<path>[^:]+):\d+: (?P<rest>.*)$")


def identity(finding: str) -> str:
    """Baseline identity with the line number stripped.

    Findings used to be diffed verbatim against the baseline, so a refactor that
    merely added or removed lines *above* an already-known offender re-reported
    it as NEW. A 96-file corner-radius migration produced 5 such phantom
    regressions — all of them structs that were already in the baseline and had
    not been touched, just pushed up by 8 lines.

    That failure mode is worse than noise: it trains people to regenerate the
    baseline to get green, which silently absorbs genuine new debt at the same
    time. ops/ui_token_lint.py already solved this by keying on
    `<relpath>::<pattern>::<snippet>` instead of the line; this mirrors it.

    The baseline FILE keeps its line numbers — they are useful to a human
    reading it — they are just not part of the comparison key.
    """
    m = _LINE_KEYED.match(finding)
    return f"{m.group('path')}: {m.group('rest')}" if m else finding


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
        known = {identity(b) for b in baseline_items}
        new = sorted(f for f in findings if identity(f) not in known)
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
