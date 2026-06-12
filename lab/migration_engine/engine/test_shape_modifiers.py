#!/usr/bin/env python3
"""Shape-geometry modifier resolution gate (clipShape skin.radii / Circle; overlay color).

The catalog histogram flagged `.clipShape` (×5) and `.overlay` (×12) as top unparsed
modifiers. A slice of each is deterministically derivable at component scope:

  - clipShape(RoundedRectangle(cornerRadius: skin.radii.X))  → border-radius var
    (skin.radii.card/overlay == AppRadius.md == --radius-md; control/chip/tiny == sm).
  - clipShape(Circle())                                       → border-radius:50%
  - overlay(<colorToken>)  (the Divider().overlay(palette.x) tint idiom) → background color

The deliberately-NOT-derivable forms stay honest backlog and are NOT asserted here:
  - clipShape(shape) / clipShape(UnevenRoundedRectangle(...))  (bare var / no-CSS-shape)

The overlay SUB-VIEW form (`overlay(alignment:) { subview }`) now has its own layer model —
see test_overlay.py / overlay_layer.swift. Only the overlay COLOR-tint idiom remains here.

This is both the IR gate (dumper emits the right modifier record) and the CSS gate
(generate_css emits the right declaration). Run:
  uv run python lab/migration_engine/engine/test_shape_modifiers.py
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

BIN = ROOT / "lab/swift_ast_dumper/.build/debug/swift-ast-dumper"
FIXTURE = ROOT / "lab/swift_ast_dumper/fixtures/shape_modifiers.swift"

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

    # --- IR: clipShape skin.radii resolves to a radius alias (no unparsed) -----------
    m = _mods(ir, "ClipSkinRadiiCard")
    check("IR clipShape(skin.radii.card) → background radius AppRadius.md",
          any(x["name"] == "background" and x.get("radius") == "AppRadius.md" for x in m),
          f"mods={m} unparsed={_struct(ir,'ClipSkinRadiiCard')['root']['unparsed']}")

    m = _mods(ir, "ClipSkinRadiiControl")
    check("IR clipShape(appSkin.radii.control) → background radius AppRadius.sm",
          any(x["name"] == "background" and x.get("radius") == "AppRadius.sm" for x in m),
          f"mods={m} unparsed={_struct(ir,'ClipSkinRadiiControl')['root']['unparsed']}")

    # --- IR: clipShape(Circle()) → shape circle ----------------------------------
    m = _mods(ir, "ClipCircle")
    check("IR clipShape(Circle()) → background shape circle",
          any(x["name"] == "background" and x.get("shape") == "circle" for x in m),
          f"mods={m} unparsed={_struct(ir,'ClipCircle')['root']['unparsed']}")

    # --- regression: existing AppRadius + Capsule still work ----------------------
    m = _mods(ir, "ClipAppRadius")
    check("IR (regression) clipShape(RoundedRectangle AppRadius.md) → radius md",
          any(x["name"] == "background" and x.get("radius") == "AppRadius.md" for x in m), str(m))
    m = _mods(ir, "ClipCapsule")
    check("IR (regression) clipShape(Capsule) → shape capsule",
          any(x["name"] == "background" and x.get("shape") == "capsule" for x in m), str(m))

    # --- IR/CSS: standalone .opacity(literal) → view-level alpha ------------------
    m = _mods(ir, "OpacityLiteral")
    check("IR .opacity(0.4) → opacity modifier value 0.4",
          any(x["name"] == "opacity" and abs(float(x.get("value", -1)) - 0.4) < 1e-9 for x in m),
          f"mods={m} unparsed={_struct(ir,'OpacityLiteral')['root']['unparsed']}")
    c = _css(ir, "OpacityLiteral")
    check("CSS .opacity(0.4) → opacity: 0.4", "opacity: 0.4" in c, c)

    # honesty: .opacity(ternary) must NOT fabricate a value → honest unparsed (no credit).
    root_t = _struct(ir, "OpacityTernary")["root"]
    check("IR .opacity(ternary) → honest unparsed (no fabricated value)",
          ".opacity" in root_t["unparsed"]
          and not any(x["name"] == "opacity" for x in root_t["modifiers"]),
          f"mods={root_t['modifiers']} unparsed={root_t['unparsed']}")

    # --- CSS: declarations are correct ------------------------------------------
    c = _css(ir, "ClipSkinRadiiCard")
    check("CSS clipShape(skin.radii.card) → border-radius var(--radius-md)",
          "border-radius: var(--radius-md)" in c, c)
    c = _css(ir, "ClipSkinRadiiControl")
    check("CSS clipShape(appSkin.radii.control) → border-radius var(--radius-sm)",
          "border-radius: var(--radius-sm)" in c, c)
    c = _css(ir, "ClipCircle")
    check("CSS clipShape(Circle()) → border-radius: 50%",
          "border-radius: 50%" in c, c)

    print(f"\n{'ALL GREEN' if not fails else str(len(fails)) + ' FAILURE(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
