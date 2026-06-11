#!/usr/bin/env python3
"""Smoke regression for migration engine v0. Pins the holdout hit-rate floor so a
mapper/applier regression can't silently rot the numbers in V0_REPORT.md.

Run: uv run python lab/migration_engine/engine/test_engine_v0.py   (exits non-zero on fail)
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENG = ROOT / "lab/migration_engine/engine"
sys.path.insert(0, str(ENG))

import extract_swiftui as ex  # noqa: E402
import generate_css as gen    # noqa: E402
import eval_holdout as ev     # noqa: E402

VIEWS = ROOT / "ios/BooksAndVocab/Views/Vocabulary/Components"
HAND = ROOT / "web/src/surfaces/notebook/notebook.css"
hand_css = HAND.read_text(encoding="utf-8")

CASES = [
    (VIEWS / "NotebookReviewActionBar.swift", "NotebookReviewActionBar", "nb-actionbar", 1.0),
    (VIEWS / "NotebookHeaderPillLabel.swift", "NotebookHeaderPillLabel", "nb-pill", 0.70),
]

failures = []
total_hit = total_scored = 0
for path, struct, cls, floor in CASES:
    ir = ex.extract_file(path)
    s = next(s for s in ir["structs"] if s["name"] == struct)
    css, stats = gen.emit_css(s, cls)
    res = ev.evaluate(ev.parse_block(hand_css, cls), ev.parse_block(css, cls))
    total_hit += len(res["hit"])
    total_scored += res["scored_declarations"]
    print(f"{cls}: hit_rate={res['hit_rate']*100:.1f}% (floor {floor*100:.0f}%) "
          f"L1={stats['L1']} L2={stats['L2']} orphan={stats['orphan']}")
    if res["hit_rate"] < floor:
        failures.append(f"{cls} {res['hit_rate']:.3f} < floor {floor}")

agg = total_hit / total_scored if total_scored else 0
print(f"AGGREGATE hit_rate={agg*100:.1f}% ({total_hit}/{total_scored})")
if agg < 0.80:
    failures.append(f"aggregate {agg:.3f} < 0.80")

if failures:
    print("FAIL:", "; ".join(failures))
    sys.exit(1)
print("PASS")
