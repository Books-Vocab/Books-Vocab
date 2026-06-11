#!/usr/bin/env python3
"""
eval_holdout.py — L3 declaration-level holdout evaluation (migration engine v0).

v0 generalization score = declaration hit rate (NOT pixel parity — that needs TSX
structure generation, out of scope). We treat an already-aligned hand surface block
as the holdout oracle: feed its SwiftUI source through extract→generate, then diff
the engine CSS declarations against the hand CSS declarations of the matching class.

A declaration = (property, normalized-value). Classification per hand declaration:
  HIT      — engine emits same property with an equivalent value
  DEVIATE  — engine emits the property but a different value
  MISS     — engine does not emit the property at all
Plus engine EXTRA declarations the hand block doesn't have (usually defaults).

Equivalence normalization folds css-var ↔ resolved-px and color-mix forms so a
token reference and its literal px aren't counted as a deviation.

Run: uv run python lab/migration_engine/engine/eval_holdout.py \
        --hand <hand.css> --engine <engine.css> --class <selector> [--json]
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# token var → resolved value, to fold engine `var(--sp-3)` against hand `12px` etc.
VAR_PX = {
    "--sp-1": "4px", "--sp-2": "8px", "--sp-3": "12px", "--sp-4": "16px",
    "--sp-5": "20px", "--sp-6": "24px", "--sp-7": "32px",
    "--sp-micro": "2px", "--sp-tiny": "3px", "--sp-hairline": "1px",
    "--radius-md": "8px", "--radius-lg": "12px", "--radius-pill": "999px",
    "--radius-card": "8px",
}
# props the engine intentionally does not model (leaf type metrics that need per-glyph
# measurement, not structure) — excluded from the MISS denominator so the score reflects
# what the engine *targets*. v1 PROMOTED display / justify-content / gap INTO scope: the
# child-tree IR now derives them structurally, so they are scored, not skipped.
OUT_OF_SCOPE_PROPS = {
    "box-sizing",            # rendering reset, not a layout intent the IR expresses
    "font-variant-numeric",  # leaf .monospacedDigit() type metric
    "-webkit-text-stroke",   # songti bold-sim L2, per-glyph measured
    "line-height",           # leaf type metric (UIKit line box), measured
    "margin",                # page-anchor positioning (e.g. chevron rides the fold seam)
    "position", "z-index",   # stacking-context anchors, page-local not platform delta
}


def parse_block(css: str, cls: str) -> dict[str, str]:
    """Extract declarations from `.cls { ... }`. Returns {prop: value}. Strips
    comments. Keeps last value if duplicated."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # find the block for this exact class
    pat = re.compile(r"\." + re.escape(cls) + r"\s*\{(.*?)\}", re.S)
    m = pat.search(css)
    if not m:
        return {}
    decls = {}
    for line in m.group(1).split(";"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        prop, _, val = line.partition(":")
        decls[prop.strip()] = val.strip()
    return decls


def norm(val: str) -> str:
    v = val.strip().lower()
    # fold var(--x) → resolved px if known
    mv = re.fullmatch(r"var\((--[\w-]+)\)", v)
    if mv and mv.group(1) in VAR_PX:
        return VAR_PX[mv.group(1)]
    # fold radius-pill / 999px / 50%
    if v in ("var(--radius-pill)", "999px", "9999px"):
        return "pill"
    # collapse whitespace inside color-mix / functions
    v = re.sub(r"\s+", " ", v)
    return v


def _padding_pair(decls: dict[str, str]) -> tuple[str, str] | None:
    """Fold shorthand `padding: V H` and longhand padding-block/inline into a
    canonical (block, inline) px pair so the two notations compare equal."""
    if "padding" in decls:
        parts = decls["padding"].split()
        if len(parts) == 2:
            return norm(parts[0]), norm(parts[1])  # V H
        if len(parts) == 1:
            n = norm(parts[0])
            return n, n
    blk = decls.get("padding-block")
    inl = decls.get("padding-inline")
    if blk or inl:
        return (norm(blk) if blk else None, norm(inl) if inl else None)
    return None


def evaluate(hand: dict[str, str], engine: dict[str, str]) -> dict:
    hit, deviate, miss, oos = [], [], [], []

    # --- padding equivalence (shorthand ↔ longhand) handled first, then excluded
    hand_pad = _padding_pair(hand)
    eng_pad = _padding_pair(engine)
    padding_props = {"padding", "padding-block", "padding-inline"}
    if hand_pad is not None:
        if eng_pad is not None and hand_pad == eng_pad:
            hit.append(("padding", f"{hand_pad[0]} / {hand_pad[1]}"))
        elif eng_pad is not None:
            deviate.append(("padding", str(hand_pad), str(eng_pad)))
        else:
            miss.append(("padding", str(hand_pad)))

    for prop, hval in hand.items():
        if prop in padding_props:
            continue  # folded above
        if prop in OUT_OF_SCOPE_PROPS:
            oos.append(prop)
            continue
        if prop not in engine:
            miss.append((prop, hval))
            continue
        if norm(hval) == norm(engine[prop]):
            hit.append((prop, hval))
        else:
            # treat var-vs-px equivalence already folded; also accept border vs
            # border-width when hand splits them — v0 keeps simple
            deviate.append((prop, hval, engine[prop]))
    extra = [(p, engine[p]) for p in engine
             if p not in hand and p not in padding_props]
    scored = len(hit) + len(deviate) + len(miss)
    rate = (len(hit) / scored) if scored else 0.0
    return {
        "scored_declarations": scored,
        "hit": hit, "deviate": deviate, "miss": miss,
        "out_of_scope_skipped": oos, "engine_extra": extra,
        "hit_rate": round(rate, 4),
    }


def main(argv: list[str]) -> int:
    opts = {}
    flags = set()
    for k, a in enumerate(argv):
        if a == "--json":
            flags.add("json")
        elif a.startswith("--") and k + 1 < len(argv):
            opts[a[2:]] = argv[k + 1]
    for req in ("hand", "engine", "class"):
        if req not in opts:
            print("usage: eval_holdout.py --hand h.css --engine e.css --class sel [--json]",
                  file=sys.stderr)
            return 2
    hand = parse_block(Path(opts["hand"]).read_text(encoding="utf-8"), opts["class"])
    engine = parse_block(Path(opts["engine"]).read_text(encoding="utf-8"), opts["class"])
    res = evaluate(hand, engine)
    res["class"] = opts["class"]
    if "json" in flags:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print(f"=== holdout: .{opts['class']} ===")
    print(f"hit_rate = {res['hit_rate']*100:.1f}%  ({len(res['hit'])}/{res['scored_declarations']} scored decls)")
    print(f"HIT     ({len(res['hit'])}): " + ", ".join(p for p, _ in res["hit"]))
    if res["deviate"]:
        print(f"DEVIATE ({len(res['deviate'])}):")
        for p, h, e in res["deviate"]:
            print(f"    {p}: hand={h!r} engine={e!r}")
    if res["miss"]:
        print(f"MISS    ({len(res['miss'])}):")
        for p, h in res["miss"]:
            print(f"    {p}: hand={h!r}")
    print(f"out-of-scope skipped ({len(res['out_of_scope_skipped'])}): "
          + ", ".join(res["out_of_scope_skipped"]))
    print(f"engine extra ({len(res['engine_extra'])}): "
          + ", ".join(p for p, _ in res["engine_extra"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
