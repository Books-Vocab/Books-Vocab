#!/usr/bin/env python3
"""Cross-symbol custom-ViewModifier resolution gate (the §next-stage capability).

Real SwiftUI leans on app-defined `extension View` modifiers and `ViewModifier`
structs. A regex parser is blind to them; an AST front-end with a symbol table can
resolve them. This pins the three expansion fates the resolver must distinguish:

  (1) inlinable pure modifier-chain on `content`  → spliced as real modifiers
  (2) presentation chain (terminates in .sheet/…) → counted as `scoped` (no coverage credit)
  (3) structural wrap (content becomes a child)    → honest `unparsed` (no false credit)

Honesty contract: a custom modifier may ONLY earn coverage when it provably expands
to a pure modifier chain. Presentation/structural fates must NOT inflate the metric.

Run: uv run python lab/migration_engine/engine/test_custom_modifier.py
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "lab/swift_ast_dumper/.build/debug/swift-ast-dumper"
FIXTURE = ROOT / "lab/swift_ast_dumper/fixtures/custom_modifiers.swift"

PASS, FAIL, SKIP = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m", "\033[33mSKIP\033[0m"


def main() -> int:
    if not BIN.exists():
        print(f"{SKIP}  AST dumper not built ({BIN.relative_to(ROOT)})")
        return 0

    out = subprocess.run([str(BIN), str(FIXTURE)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(f"{FAIL}  dumper exit {out.returncode}: {out.stderr.strip()[:200]}")
        return 1
    ir = json.loads(out.stdout)

    demo = next((s for s in ir["structs"] if s["name"] == "Demo"), None)
    if demo is None:
        print(f"{FAIL}  Demo struct not found")
        return 1
    root = demo["root"]
    mod_names = [m.get("name") for m in root.get("modifiers", [])]
    scoped = root.get("scoped", [])
    unparsed = root.get("unparsed", [])

    fails = []

    # (1) myCanvas → content.background(...) → a real background modifier spliced in
    if "background" in mod_names:
        print(f"{PASS}  (1) inlinable myCanvas resolved → background modifier")
    else:
        print(f"{FAIL}  (1) myCanvas not resolved; modifiers={mod_names} unparsed={unparsed}")
        fails.append("inlinable not resolved")

    # (2) myGate → mySheet → .sheet → scoped (NOT coverage)
    if ".myGate" in scoped:
        print(f"{PASS}  (2) presentation myGate → scoped (no coverage credit)")
    else:
        print(f"{FAIL}  (2) myGate not scoped; scoped={scoped} unparsed={unparsed}")
        fails.append("presentation not scoped")

    # (3) myWrap → AppSectionCard{content} → structural → honest unparsed
    if ".myWrap" in unparsed:
        print(f"{PASS}  (3) structural myWrap → honest unparsed (no false credit)")
    else:
        print(f"{FAIL}  (3) myWrap not unparsed; unparsed={unparsed} mods={mod_names} scoped={scoped}")
        fails.append("structural mis-credited")

    # honesty: the structural/presentation fates must not have leaked into modifiers
    if len(mod_names) == 1 and mod_names == ["background"]:
        print(f"{PASS}  honesty: only the provable inlinable earned a modifier")
    else:
        print(f"{FAIL}  honesty: unexpected modifiers {mod_names}")
        fails.append("over-credit")

    # explicit `.modifier(Struct())` form resolves through the same machinery
    demo2 = next((s for s in ir["structs"] if s["name"] == "Demo2"), None)
    if demo2 is None:
        print(f"{FAIL}  Demo2 struct not found")
        fails.append("demo2 missing")
    else:
        r2 = demo2["root"]
        m2 = [m.get("name") for m in r2.get("modifiers", [])]
        u2 = r2.get("unparsed", [])
        if m2 == ["background"] and any("WrapMod" in x for x in u2):
            print(f"{PASS}  (4) explicit .modifier(): CanvasMod→background, WrapMod→unparsed")
        else:
            print(f"{FAIL}  (4) explicit .modifier() mishandled; mods={m2} unparsed={u2}")
            fails.append("explicit modifier")

    print(f"\n{'ALL GREEN' if not fails else str(len(fails)) + ' FAILURE(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
