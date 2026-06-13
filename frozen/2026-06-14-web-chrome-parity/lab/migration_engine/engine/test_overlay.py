#!/usr/bin/env python3
"""Overlay-layer modifier resolution gate (the histogram's #1 unparsed: `.overlay` ×12).

All 12 unparsed `.overlay` sites are the trailing-closure SUB-VIEW form
(`.overlay(alignment:) { badge }` / `.overlay { veil }`) — the paren-form
`.overlay(Shape().stroke(...))` border idiom already resolves via findStrokeCall.

This models the overlay as a faithful CSS layer:
  container     → position: relative
  overlay layer → position:absolute; inset:0; display:flex; align-items/justify-content
                  derived from the SwiftUI Alignment (layer fills the overlaid view; the
                  flex box places the child where SwiftUI's alignment would).

Both gates: IR (dumper emits an `overlay` modifier carrying `alignment`) and CSS
(generate_css emits position:relative + the aligned layer rule). The overlay child's
INTERIOR is deliberately NOT transpiled (separate sub-tree, like stack children) and the
bare-color tint form stays honest unparsed — both asserted here.

Run: uv run python lab/migration_engine/engine/test_overlay.py
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENG = ROOT / "lab/migration_engine/engine"
sys.path.insert(0, str(ENG))
import generate_css as gen  # noqa: E402
from ir_contract import validate_ir  # noqa: E402

BIN = ROOT / "lab/swift_ast_dumper/.build/debug/swift-ast-dumper"
FIXTURE = ROOT / "lab/swift_ast_dumper/fixtures/overlay_layer.swift"

PASS, FAIL, SKIP = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m", "\033[33mSKIP\033[0m"


def _struct(ir: dict, name: str) -> dict:
    return next(s for s in ir["structs"] if s["name"] == name)


def _mods(ir: dict, name: str) -> list[dict]:
    return _struct(ir, name)["root"]["modifiers"]


def _css(ir: dict, name: str) -> str:
    css, _ = gen.emit_css(_struct(ir, name), "probe")
    return css


def main() -> int:
    if not BIN.exists():
        print(f"{SKIP}  AST dumper not built ({BIN.relative_to(ROOT)})")
        return 0

    out = subprocess.run([str(BIN), str(FIXTURE)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(f"{FAIL}  dumper exit {out.returncode}: {out.stderr.strip()[:200]}")
        return 1
    ir = json.loads(out.stdout)

    fails: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"{PASS}  {label}")
        else:
            print(f"{FAIL}  {label}  {detail}")
            fails.append(label)

    # IR validates against the contract (overlay modifier admitted by the seam).
    check("IR contract OK (overlay modifier admitted)", not validate_ir(ir), str(validate_ir(ir))[:300])

    def ov(name: str) -> dict | None:
        return next((m for m in _mods(ir, name) if m["name"] == "overlay"), None)

    # --- IR: overlay modifier carries the alignment -----------------------------------
    for struct, align in [
        ("OverlayTopTrailing", "topTrailing"),
        ("OverlayBottomLeading", "bottomLeading"),
        ("OverlayBottomEdge", "bottom"),
        ("OverlayCenterDefault", "center"),
    ]:
        m = ov(struct)
        check(f"IR {struct} → overlay modifier alignment={align}",
              m is not None and m.get("alignment") == align,
              f"mods={_mods(ir, struct)} unparsed={_struct(ir, struct)['root']['unparsed']}")

    # --- CSS: container position:relative + faithful flex layer ------------------------
    align_flex = {
        "topTrailing": ("flex-start", "flex-end"),
        "bottomLeading": ("flex-end", "flex-start"),
        "bottom": ("flex-end", "center"),
        "center": ("center", "center"),
    }
    for struct, align in [("OverlayTopTrailing", "topTrailing"),
                          ("OverlayBottomLeading", "bottomLeading"),
                          ("OverlayBottomEdge", "bottom"),
                          ("OverlayCenterDefault", "center")]:
        c = _css(ir, struct)
        ai, jc = align_flex[align]
        check(f"CSS {struct} → container position: relative", "position: relative" in c, c)
        check(f"CSS {struct} → layer position:absolute; inset:0",
              "position: absolute" in c and "inset: 0" in c, c)
        check(f"CSS {struct} → layer align-items:{ai}; justify-content:{jc}",
              f"align-items: {ai}" in c and f"justify-content: {jc}" in c, c)

    # --- regression: stroke-border overlay is STILL a border, NOT a layer -------------
    m = _mods(ir, "OverlayStrokeBorder")
    check("IR (regression) overlay(Shape().stroke) → border (no overlay layer modifier)",
          any(x["name"] == "stroke" for x in m) and not any(x["name"] == "overlay" for x in m),
          str(m))
    c = _css(ir, "OverlayStrokeBorder")
    check("CSS (regression) overlay(stroke) → border, no position:absolute",
          "border:" in c and "position: absolute" not in c, c)

    # --- honesty: bare-color overlay is a tint, NOT a layer → honest unparsed ----------
    root = _struct(ir, "OverlayColorTint")["root"]
    check("IR overlay(<bare color>) → honest unparsed (no fabricated layer)",
          ".overlay" in root["unparsed"] and not any(x["name"] == "overlay" for x in root["modifiers"]),
          f"mods={root['modifiers']} unparsed={root['unparsed']}")

    print(f"\n{'ALL GREEN' if not fails else str(len(fails)) + ' FAILURE(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
