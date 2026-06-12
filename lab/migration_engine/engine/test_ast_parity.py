#!/usr/bin/env python3
"""AST-vs-regex parser parity gate.

Proves the seam swap is safe: feeding the SwiftSyntax AST dumper's IR through the SAME
generate_css produces output that is (a) contract-valid, (b) no worse hit-rate than the
regex parser, and (c) has fewer/equal unparsed nodes. This is the regression that keeps
the AST front-end honest as it grows — structure first (unparsed↓), pixels not worse.

The AST dumper is a built Swift binary; if it isn't built yet this test SKIPS loudly
rather than failing (build with: swift build --package-path lab/swift_ast_dumper).

Run: uv run python lab/migration_engine/engine/test_ast_parity.py
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENG = ROOT / "lab/migration_engine/engine"
sys.path.insert(0, str(ENG))

import extract_swiftui as ex   # noqa: E402
import generate_css as gen     # noqa: E402
import eval_holdout as ev      # noqa: E402
from ir_contract import validate_ir  # noqa: E402

BIN = ROOT / "lab/swift_ast_dumper/.build/debug/swift-ast-dumper"

# (swift src, struct, css class, hand css) — the self-contained leaf components.
CASES = [
    ("ios/BooksAndVocab/Views/Vocabulary/Components/NotebookHeaderPillLabel.swift",
     "NotebookHeaderPillLabel", "nb-pill", "web/src/surfaces/notebook/notebook.css"),
]

PASS, FAIL, SKIP = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m", "\033[33mSKIP\033[0m"


def _count_unparsed(node: dict) -> int:
    n = len(node.get("unparsed", []) or [])
    for c in node.get("children", []) or []:
        n += _count_unparsed(c)
    return n


def _ast_ir(src: str, struct: str) -> dict:
    out = subprocess.run([str(BIN), str(ROOT / src), "--struct", struct],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def main() -> int:
    if not BIN.exists():
        print(f"{SKIP}  AST dumper not built ({BIN.relative_to(ROOT)}); "
              f"run: swift build --package-path lab/swift_ast_dumper")
        return 0

    fails = []
    for src, struct, cls, hand_path in CASES:
        hand = ev.parse_block((ROOT / hand_path).read_text(encoding="utf-8"), cls)

        # regex baseline
        r_ir = ex.extract_file(ROOT / src)
        r_s = next(s for s in r_ir["structs"] if s["name"] == struct)
        r_css, _ = gen.emit_css(r_s, cls)
        r_hit = ev.evaluate(hand, ev.parse_block(r_css, cls))["hit_rate"]
        r_unp = _count_unparsed(r_s["root"])

        # AST candidate
        a_ir = _ast_ir(src, struct)
        errs = validate_ir(a_ir)
        if errs:
            fails.append(f"{cls}: AST IR violates contract: {errs[:3]}")
            continue
        a_s = next(s for s in a_ir["structs"] if s["name"] == struct)
        a_css, _ = gen.emit_css(a_s, cls)
        a_hit = ev.evaluate(hand, ev.parse_block(a_css, cls))["hit_rate"]
        a_unp = _count_unparsed(a_s["root"])

        ok = a_hit >= r_hit and a_unp <= r_unp
        verdict = PASS if ok else FAIL
        print(f"{verdict}  {cls}: AST hit={a_hit*100:.1f}% (regex {r_hit*100:.1f}%)  "
              f"AST unparsed={a_unp} (regex {r_unp})")
        if not ok:
            fails.append(f"{cls}: AST hit {a_hit:.3f} < regex {r_hit:.3f} "
                         f"OR unparsed {a_unp} > {r_unp}")

    print(f"\n{'ALL GREEN' if not fails else str(len(fails)) + ' FAILURE(S)'}")
    for f in fails:
        print(f"  - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
