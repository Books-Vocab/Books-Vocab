#!/usr/bin/env python3
"""
extract_swiftui.py — modifier-level SwiftUI extractor (migration engine v0).

Scope (v0, deliberately thin): a single SwiftUI `View` struct's `body` is reduced
to a flat list of *element* records, each carrying the layout/visual modifiers we
can map to CSS. This is NOT a Swift AST parser — it is a regex + indentation
heuristic tuned to the modifier vocabulary that the parity rewrite actually used
(padding / spacing / font(role) / foregroundStyle(token) / frame / cornerRadius /
background fill / overlay stroke). Anything it can't classify is emitted as an
`unmapped` note so the downstream report can count the miss honestly.

Output: intermediate representation (IR) JSON on stdout (or --out file):
  { "source": <path>, "structs": [ { "name", "elements": [ {element record} ] } ] }

Each element record:
  { "kind": "Text|Image|HStack|VStack|Spacer|container|...",
    "selector_hint": <best-guess CSS class from the hand surface, or null>,
    "modifiers": [ {"name", "args": {...}, "raw"} ],
    "unmapped": [ raw-line, ... ] }

Run: uv run python lab/migration_engine/engine/extract_swiftui.py <view.swift> [--out f.json]
"""
from __future__ import annotations
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --- token-scalar dictionaries (names → meaning); the *numbers* live in the web
#     token css and are resolved by generate_css.py. Here we only need the symbolic
#     identity so L1 can do name→var lookup. ---------------------------------------

SPACING_TOKENS = {
    "AppSpacing.hairline", "AppSpacing.microGap", "AppSpacing.tinyGap",
    "AppSpacing.s1", "AppSpacing.s2", "AppSpacing.s3", "AppSpacing.s4",
    "AppSpacing.s5", "AppSpacing.s6", "AppSpacing.s7", "AppSpacing.s8",
    "AppSpacing.s9", "AppSpacing.s10",
}
RADIUS_TOKENS = {
    "AppRadius.none", "AppRadius.xs", "AppRadius.sm", "AppRadius.md",
    "AppRadius.lg", "AppRadius.xl", "AppRadius.pill", "AppRadius.card",
    "AppRadius.hairline",
}

# font role → (family, size_pt, weight_intent). Resolved from AppSkin+BaseValues /
# AppFonts. v0 carries the roles the slice needs; extend per surface.
FONT_ROLES = {
    "caption": {"family": "sans", "size": 12, "weight": "regular"},
    "caption2": {"family": "sans", "size": 11, "weight": "regular"},
    "sectionTitle": {"family": "serif", "size": 18, "weight": "bold"},
    "body": {"family": "sans", "size": 17, "weight": "regular"},
}

# color token (iOS palette key) → web css var name. Derived from kg-tokens.css.
COLOR_TOKENS = {
    "primaryText": "--text-primary",
    "secondaryText": "--text-secondary",
    "tertiaryText": "--text-tertiary",
    "mutedFill": "--muted-fill",
    "divider": "--divider",
    "brandHero": "--brand-hero",
    "onBrandHero": "--on-brand-hero",
    "buttonIdleFill": "--button-idle-fill",
    "accent": "--accent",
    "cardBackground": "--card-bg",
    "pageBackground": "--page-bg",
}


@dataclass
class Element:
    kind: str
    selector_hint: str | None = None
    modifiers: list[dict] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)


# --- regex vocabulary --------------------------------------------------------

RE_PADDING = re.compile(
    r"\.padding\(\s*(?:\.(?P<edge>all|horizontal|vertical|top|bottom|leading|trailing)\s*,\s*)?(?P<val>[^)]+?)\s*\)"
)
RE_FRAME = re.compile(r"\.frame\(\s*(?P<args>[^)]*)\)")
RE_FONT = re.compile(r"\.font\(\s*(?:appSkin|skin)\.typography\.(?P<role>\w+)(?P<chain>.*)\)")
RE_FONT_DIRECT = re.compile(r"\.font\(\s*AppFonts\.(?P<fn>serif|sans|mono)\(\s*size:\s*(?P<size>\d+)(?:\s*,\s*bold:\s*(?P<bold>true|false))?\s*\)")
RE_FG = re.compile(r"\.foregroundStyle\(\s*(?:skin|appSkin)\.palette\.(?P<tok>\w+)")
RE_FG2 = re.compile(r"\.foregroundStyle\(\s*AppColors\.(?P<tok>\w+)\s*\)")
RE_STACK = re.compile(r"\b(?P<kind>HStack|VStack|ZStack)\(\s*(?:.*?spacing:\s*(?P<sp>[^,)]+))?")
RE_SPACER = re.compile(r"\bSpacer\(\s*(?:minLength:\s*(?P<ml>[^)]+))?\)")
RE_FRAME_MINW = re.compile(r"minWidth:\s*(?P<v>\d+)")
RE_RRECT = re.compile(r"RoundedRectangle\(cornerRadius:\s*(?P<r>[^,)]+)")
RE_FILL = re.compile(r"\.fill\(\s*(?:skin|appSkin)\.palette\.(?P<tok>\w+)(?P<chain>[^)]*)\)")
RE_STROKE = re.compile(r"\.stroke\(\s*(?:skin|appSkin)\.palette\.(?P<tok>\w+)[^,]*,\s*lineWidth:\s*(?P<lw>[^)]+)\)")
RE_TEXT = re.compile(r"\bText\(")
RE_IMAGE = re.compile(r"\bImage\(systemName:")


def _is_token(expr: str, table: set[str]) -> str | None:
    expr = expr.strip()
    return expr if expr in table else None


def _parse_padding_val(val: str) -> dict:
    """Return {kind: token|expr|literal, value, raw}. Handles AppSpacing.sN +/- k."""
    val = val.strip()
    if val in SPACING_TOKENS:
        return {"kind": "token", "token": val, "raw": val}
    # composite like `AppSpacing.s2 + 2` or `AppSpacing.s2 - AppSpacing.hairline`
    m = re.match(r"(AppSpacing\.\w+)\s*([+\-])\s*(AppSpacing\.\w+|\d+)", val)
    if m:
        return {"kind": "expr", "base": m.group(1), "op": m.group(2),
                "addend": m.group(3), "raw": val}
    if re.fullmatch(r"\d+", val):
        return {"kind": "literal", "value": int(val), "raw": val}
    return {"kind": "unknown", "raw": val}


def _join_chained_modifiers(lines: list[str]) -> list[str]:
    """Collapse a modifier whose argument spans multiple lines (balanced parens)
    into one logical line, e.g. multi-line `.background( RoundedRectangle(...).fill(...) )`.
    Heuristic: when a stripped line ends on an unbalanced '(' for a `.background(` /
    `.overlay(` / `.frame(` / `.font(`, keep consuming until parens rebalance."""
    out: list[str] = []
    buf = ""
    depth = 0
    triggers = (".background(", ".overlay(", ".frame(", ".font(", ".fill(", ".stroke(")
    for raw in lines:
        s = raw.strip()
        if buf:
            buf += " " + s
            depth += s.count("(") - s.count(")")
            if depth <= 0:
                out.append(buf)
                buf = ""
                depth = 0
            continue
        bal = s.count("(") - s.count(")")
        if bal > 0 and any(t in s for t in triggers):
            buf = s
            depth = bal
        else:
            out.append(s)
    if buf:
        out.append(buf)
    return out


def parse_struct_body(name: str, lines: list[str]) -> Element:
    """v0 collapses a struct's body into one synthetic 'root' element carrying every
    modifier it can recognize, plus child Text/Image/Spacer markers. This is enough
    for a flat declaration-level diff against the hand CSS of the matching block; a
    real tree is v1."""
    root = Element(kind="container", selector_hint=None)
    lines = _join_chained_modifiers(lines)
    joined = "\n".join(lines)

    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("//"):
            continue

        matched = False

        # padding
        for m in RE_PADDING.finditer(s):
            edge = m.group("edge") or "all"
            pv = _parse_padding_val(m.group("val"))
            root.modifiers.append({"name": "padding", "edge": edge, "value": pv, "raw": s})
            matched = True

        # font role
        m = RE_FONT.search(s)
        if m:
            role = m.group("role")
            chain = m.group("chain") or ""
            weight = None
            wm = re.search(r"\.weight\(\.(\w+)\)", chain)
            if wm:
                weight = wm.group(1)
            root.modifiers.append({"name": "font", "role": role, "weight_override": weight, "raw": s})
            matched = True
        m = RE_FONT_DIRECT.search(s)
        if m:
            root.modifiers.append({"name": "font_direct", "family": m.group("fn"),
                                   "size": int(m.group("size")),
                                   "bold": m.group("bold") == "true", "raw": s})
            matched = True

        # foreground color
        for rgx in (RE_FG, RE_FG2):
            m = rgx.search(s)
            if m:
                root.modifiers.append({"name": "foreground", "token": m.group("tok"), "raw": s})
                matched = True

        # frame
        m = RE_FRAME.search(s)
        if m:
            args = m.group("args")
            mw = RE_FRAME_MINW.search(args)
            root.modifiers.append({"name": "frame",
                                   "min_width": int(mw.group("v")) if mw else None,
                                   "raw": s})
            matched = True

        # background fill (RoundedRectangle / Capsule)
        for m in RE_FILL.finditer(s):
            opacity = None
            om = re.search(r"\.fill\([^)]*\.opacity\(([\d.]+)\)", s)
            if om:
                opacity = float(om.group(1))
            shape = "capsule" if "Capsule" in s else ("rrect" if "RoundedRectangle" in joined else "shape")
            radius = None
            rm = RE_RRECT.search(s)
            if rm:
                radius = rm.group("r").strip()
            root.modifiers.append({"name": "background", "token": m.group("tok"),
                                   "opacity": opacity, "shape": shape,
                                   "radius": radius, "raw": s})
            matched = True
        # Capsule fill without palette captured above still flagged via shape token
        if "Capsule(style: .continuous).fill(" in s and not RE_FILL.search(s):
            fm = re.search(r"\.fill\((\w+)\)", s)
            root.modifiers.append({"name": "background", "token": fm.group(1) if fm else None,
                                   "opacity": None, "shape": "capsule", "radius": None,
                                   "param": True, "raw": s})
            matched = True

        # overlay stroke
        m = RE_STROKE.search(s)
        if m:
            root.modifiers.append({"name": "stroke", "token": m.group("tok"),
                                   "line_width": m.group("lw").strip(), "raw": s})
            matched = True

        # rounded rectangle radius alone (for shape-only cases captured w/ background)
        # stack containers
        m = RE_STACK.search(s)
        if m:
            sp = m.group("sp")
            root.modifiers.append({"name": "stack", "kind": m.group("kind"),
                                   "spacing": _parse_padding_val(sp) if sp else None,
                                   "raw": s})
            matched = True

        # spacer
        m = RE_SPACER.search(s)
        if m:
            root.modifiers.append({"name": "spacer", "min_length": (m.group("ml") or "").strip() or None, "raw": s})
            matched = True

        # leaf text/image markers (presence only, v0)
        if RE_TEXT.search(s):
            root.modifiers.append({"name": "leaf", "kind": "Text", "raw": s})
            matched = True
        if RE_IMAGE.search(s):
            root.modifiers.append({"name": "leaf", "kind": "Image", "raw": s})
            matched = True

        if not matched and any(tok in s for tok in (
            ".padding", ".font", ".frame", ".background", ".overlay",
            ".foreground", "Stack(", "Spacer(", "RoundedRectangle", "Capsule")):
            root.unmapped.append(s)

    return root


def extract_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    structs = []
    # find each `struct X ... : View {` and its `var body: some View {` block
    i = 0
    while i < len(lines):
        m = re.match(r"\s*struct\s+(\w+)(?:<[^>]+>)?\s*:\s*View\b", lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        # locate body block via brace matching from `var body`
        body_start = None
        for j in range(i, min(i + 200, len(lines))):
            if re.search(r"var\s+body\s*:\s*some\s+View\s*\{", lines[j]):
                body_start = j
                break
        if body_start is None:
            i += 1
            continue
        depth = 0
        started = False
        body_lines = []
        for j in range(body_start, len(lines)):
            depth += lines[j].count("{") - lines[j].count("}")
            body_lines.append(lines[j])
            if not started and "{" in lines[j]:
                started = True
            if started and depth <= 0:
                break
        elem = parse_struct_body(name, body_lines)
        structs.append({"name": name, "elements": [asdict(elem)]})
        i = j + 1
    return {"source": str(path), "structs": structs}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    out = None
    for k, a in enumerate(argv):
        if a == "--out" and k + 1 < len(argv):
            out = argv[k + 1]
    if not args:
        print("usage: extract_swiftui.py <view.swift> [--out f.json]", file=sys.stderr)
        return 2
    ir = extract_file(Path(args[0]))
    payload = json.dumps(ir, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(payload, encoding="utf-8")
        print(f"wrote {out} ({len(ir['structs'])} struct(s))", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
