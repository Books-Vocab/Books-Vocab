#!/usr/bin/env python3
"""Regression gate for migration engine v1 (child-tree IR + layout mapping).

Pins the holdout hit-rate floor across 4 container/pill holdouts on 3 surfaces so a
mapper/extractor regression can't silently rot the numbers in V1_REPORT.md. v1's win
over v0 is structural: the nested tree lets the engine derive display / flex-direction /
align-items / justify-content / gap, which v0 scored OUT_OF_SCOPE.

Run: uv run python lab/migration_engine/engine/test_engine_v1.py   (exits non-zero on fail)
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

VC = ROOT / "ios/BooksAndVocab/Views/Vocabulary/Components"
VS = ROOT / "ios/BooksAndVocab/Views/Vocabulary/Scenes"

# (swift path, struct, css class, hand css path, per-case floor)
CASES = [
    # v0 holdouts — notebook (container + nested pill)
    (VC / "NotebookReviewActionBar.swift", "NotebookReviewActionBar", "nb-actionbar",
     ROOT / "web/src/surfaces/notebook/notebook.css", 1.0),
    (VC / "NotebookHeaderPillLabel.swift", "NotebookHeaderPillLabel", "nb-pill",
     ROOT / "web/src/surfaces/notebook/notebook.css", 0.80),
    # v1 NEW holdouts — different surfaces, nested structure
    (VS / "ReviewFoldSurface.swift", "ReviewFoldChevronPill", "tr-chevron-pill",
     ROOT / "web/src/surfaces/today-review/today-review.css", 0.88),
    (VC / "VocabShellComponents+Actions.swift", "VocabSortPill", "vc-sort-pill",
     ROOT / "web/src/surfaces/vocabulary/vocabulary.css", 0.90),
]

AGG_FLOOR = 0.85  # whole-holdout floor (v0 container-level was 83.3%)

failures = []
total_hit = total_scored = 0
for path, struct, cls, hand_path, floor in CASES:
    ir = ex.extract_file(path)
    s = next(s for s in ir["structs"] if s["name"] == struct)
    css, stats = gen.emit_css(s, cls)
    hand = ev.parse_block(hand_path.read_text(encoding="utf-8"), cls)
    res = ev.evaluate(hand, ev.parse_block(css, cls))
    total_hit += len(res["hit"])
    total_scored += res["scored_declarations"]
    print(f"{cls}: hit_rate={res['hit_rate']*100:.1f}% (floor {floor*100:.0f}%) "
          f"L1={stats['L1']} L2={stats['L2']} orphan={stats['orphan']}")
    if res["hit_rate"] < floor:
        failures.append(f"{cls} {res['hit_rate']:.3f} < floor {floor}")

agg = total_hit / total_scored if total_scored else 0
print(f"AGGREGATE hit_rate={agg*100:.1f}% ({total_hit}/{total_scored})")
if agg < AGG_FLOOR:
    failures.append(f"aggregate {agg:.3f} < {AGG_FLOOR}")

if failures:
    print("FAIL:", "; ".join(failures))
    sys.exit(1)
print("PASS")
