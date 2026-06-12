#!/usr/bin/env python3
"""Seam contract gate: any IR parser (regex today, SwiftSyntax AST tomorrow) must emit
IR that (a) passes validate_ir and (b) is consumable by generate_css without raising.

This locks the box-tree IR as a protected interface. The AST dumper's job is to keep
this green while driving `unparsed` to zero — structure first, pixels after.

Run: uv run python lab/migration_engine/engine/test_ir_contract.py   (non-zero on fail)
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENG = ROOT / "lab/migration_engine/engine"
sys.path.insert(0, str(ENG))

import extract_swiftui as ex   # noqa: E402
import generate_css as gen     # noqa: E402
from ir_contract import validate_ir  # noqa: E402

# Real surfaces the engine already targets (same set the v1 regression pins).
VC = ROOT / "ios/BooksAndVocab/Views/Vocabulary/Components"
VS = ROOT / "ios/BooksAndVocab/Views/Vocabulary/Scenes"
RD = ROOT / "ios/BooksAndVocab/Views/Reader"
SAMPLE_SOURCES = [
    RD / "ReaderSelectionTile.swift",
    VC / "NotebookReviewActionBar.swift",
    VC / "NotebookHeaderPillLabel.swift",
    VS / "ReviewFoldSurface.swift",
    VC / "VocabShellComponents+Actions.swift",
]

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"


def _extract(path: Path) -> dict:
    """Run the regex parser → IR dict (the current front-end)."""
    return ex.extract_file(path)


def test_positive_real_ir_validates() -> list[str]:
    """Every real surface's parsed IR must pass the contract."""
    fails = []
    for src in SAMPLE_SOURCES:
        if not src.exists():
            fails.append(f"missing sample source: {src}")
            continue
        ir = _extract(src)
        errs = validate_ir(ir)
        if errs:
            fails.append(f"{src.name}: {len(errs)} contract violation(s): {errs[:3]}")
    return fails


def test_roundtrip_generate_consumes() -> list[str]:
    """Contract-valid IR must be consumable by generate_css.emit_css without raising."""
    fails = []
    for src in SAMPLE_SOURCES:
        if not src.exists():
            continue
        ir = _extract(src)
        for s in ir["structs"]:
            try:
                css, stats = gen.emit_css(s, "test-sel")
                assert isinstance(css, str) and css.strip().endswith("}"), "css malformed"
            except Exception as e:  # noqa: BLE001
                fails.append(f"{src.name}::{s['name']}: generate raised {type(e).__name__}: {e}")
    return fails


def test_negative_validator_has_teeth() -> list[str]:
    """The validator must REJECT malformed IR (otherwise it's a rubber stamp)."""
    fails = []
    bad_cases = {
        "bad node.kind": {"structs": [{"name": "X", "root": {
            "kind": "Bogus", "modifiers": [], "children": [], "unparsed": []}}]},
        "modifiers not list": {"structs": [{"name": "X", "root": {
            "kind": "VStack", "modifiers": {}, "children": [], "unparsed": []}}]},
        "padding missing value": {"structs": [{"name": "X", "root": {
            "kind": "Text", "modifiers": [{"name": "padding", "edge": "all"}],
            "children": [], "unparsed": []}}]},
        "bad value.kind": {"structs": [{"name": "X", "root": {
            "kind": "Text", "modifiers": [{"name": "padding", "edge": "all",
            "value": {"kind": "nonsense"}}], "children": [], "unparsed": []}}]},
        "struct missing root": {"structs": [{"name": "X"}]},
        "structs not list": {"structs": {}},
    }
    for label, bad in bad_cases.items():
        if not validate_ir(bad):
            fails.append(f"validator FAILED to reject: {label}")
    return fails


def main() -> int:
    suites = [
        ("positive: real IR validates", test_positive_real_ir_validates),
        ("roundtrip: generate consumes contract-valid IR", test_roundtrip_generate_consumes),
        ("negative: validator has teeth", test_negative_validator_has_teeth),
    ]
    total_fail = 0
    for name, fn in suites:
        fails = fn()
        if fails:
            total_fail += len(fails)
            print(f"{FAIL}  {name}")
            for f in fails:
                print(f"       - {f}")
        else:
            print(f"{PASS}  {name}")
    print(f"\n{'ALL GREEN' if total_fail == 0 else str(total_fail) + ' FAILURE(S)'}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
