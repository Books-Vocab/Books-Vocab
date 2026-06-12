#!/usr/bin/env python3
"""Corpus-wide regression gate for the AST front-end (catalog as the training set).

Pins the system-level loss so a parser change can't silently rot coverage:
  - node coverage floor (resolved / total decorations) — the headline loss metric
  - zero dumper crashes over the whole corpus
  - every file's IR is contract-valid (the seam holds at scale)
  - honesty invariant: no modifier `token` is fabricated from raw closure text
    (guards the §2 background-trailing-closure false-green the #962 review caught)

Run: uv run python lab/migration_engine/engine/test_catalog_coverage.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENG = ROOT / "lab/migration_engine/engine"
sys.path.insert(0, str(ENG))
import catalog_coverage as cov  # noqa: E402

# Ratchet: raise as the long tail (.overlay/.fill/.clipShape/custom modifiers) lands.
COVERAGE_FLOOR = 0.68  # current 71.5%; buffer for corpus churn

PASS, FAIL, SKIP = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m", "\033[33mSKIP\033[0m"


def main() -> int:
    if not cov.BIN.exists():
        print(f"{SKIP}  AST dumper not built ({cov.BIN.relative_to(ROOT)})")
        return 0

    r = cov.compute()
    fails = []

    cvg = r["node_coverage"]
    if cvg >= COVERAGE_FLOOR:
        print(f"{PASS}  node coverage {cvg*100:.1f}% >= floor {COVERAGE_FLOOR*100:.0f}%")
    else:
        print(f"{FAIL}  node coverage {cvg*100:.1f}% < floor {COVERAGE_FLOOR*100:.0f}%")
        fails.append("coverage below floor")

    if r["dump_failed"] == 0:
        print(f"{PASS}  0 dumper crashes over {r['files']} files")
    else:
        print(f"{FAIL}  {r['dump_failed']} dumper crash(es): {r['errors'][:3]}")
        fails.append("dumper crashes")

    if not r["contract_violations"]:
        print(f"{PASS}  all IR contract-valid ({r['contract_ok']} files)")
    else:
        print(f"{FAIL}  {len(r['contract_violations'])} contract violation(s): {r['contract_violations'][:3]}")
        fails.append("contract violations")

    if not r["junk_tokens"]:
        print(f"{PASS}  honesty: no closure-literal tokens fabricated")
    else:
        print(f"{FAIL}  {len(r['junk_tokens'])} fabricated token(s): {r['junk_tokens'][:3]}")
        fails.append("junk tokens")

    print(f"\n{'ALL GREEN' if not fails else str(len(fails)) + ' FAILURE(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
