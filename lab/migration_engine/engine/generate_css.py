#!/usr/bin/env python3
"""
generate_css.py — L1 token mapper + L2 codex applier (migration engine v1: tree-aware).

v0 consumed a FLAT modifier list and emitted only container-level declarations. It could
not see child structure, so the layout declarations every chip/row needs —
`display:(inline-)flex`, `flex-direction`, `align-items`, `justify-content`, `gap` —
were structurally invisible and scored OUT_OF_SCOPE. That was v0's measured top miss.

v1 consumes the nested tree from extract_swiftui.py. It first picks the **surface
container node** (the node whose declarations map to the hand CSS class), then emits:

  LAYOUT (the v1 unlock):
    - stack node           → display:flex; flex-direction:row|column; gap:<spacing>;
                             align-items / justify-content from the stack's axis + Spacer.
    - leaf-wrapping box     → a node that paints a background/frame around inline content
      (chip / pill / icon button) → display:inline-flex; align-items:center;
      justify-content:center  (the canonical SwiftUI "padding+background around a label"
      centering idiom). This is what makes `.nb-pill` / `.tr-chevron-pill` resolvable.

  VISUAL / GEOMETRY (carried from v0):
    - padding / font / foreground / frame / background / stroke → tokens + L2 codex.

Every output line is annotated `/* L1:token */`, `/* L2:<rule> */`, or `/* orphan */`.

Run: uv run python lab/migration_engine/engine/generate_css.py <ir.json> --selector <class> [--struct Name] [--out f.css]
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# scalar values resolved from web/src/styles/kg-tokens.css (shared SoT numbers).
SP_PX = {
    "AppSpacing.hairline": 1, "AppSpacing.microGap": 2, "AppSpacing.tinyGap": 3,
    "AppSpacing.s1": 4, "AppSpacing.s2": 8, "AppSpacing.s3": 12, "AppSpacing.s4": 16,
    "AppSpacing.s5": 20, "AppSpacing.s6": 24, "AppSpacing.s7": 32, "AppSpacing.s8": 40,
    "AppSpacing.s9": 48, "AppSpacing.s10": 64,
}
SP_VAR = {
    "AppSpacing.s1": "--sp-1", "AppSpacing.s2": "--sp-2", "AppSpacing.s3": "--sp-3",
    "AppSpacing.s4": "--sp-4", "AppSpacing.s5": "--sp-5", "AppSpacing.s6": "--sp-6",
    "AppSpacing.s7": "--sp-7", "AppSpacing.s8": "--sp-8", "AppSpacing.s9": "--sp-9",
    "AppSpacing.s10": "--sp-10", "AppSpacing.microGap": "--sp-micro",
    "AppSpacing.tinyGap": "--sp-tiny", "AppSpacing.hairline": "--sp-hairline",
}
RADIUS_VAR = {
    "AppRadius.none": "--radius-none", "AppRadius.xs": "--radius-xs",
    "AppRadius.sm": "--radius-sm", "AppRadius.md": "--radius-md",
    "AppRadius.lg": "--radius-lg", "AppRadius.xl": "--radius-xl",
    "AppRadius.pill": "--radius-pill", "AppRadius.card": "--radius-card",
}
COLOR_TOKENS = {
    "primaryText": "--text-primary", "secondaryText": "--text-secondary",
    "tertiaryText": "--text-tertiary", "mutedFill": "--muted-fill",
    "divider": "--divider", "brandHero": "--brand-hero",
    "onBrandHero": "--on-brand-hero", "buttonIdleFill": "--button-idle-fill",
    "accent": "--accent", "cardBackground": "--card-bg", "pageBackground": "--page-bg",
}
# font role → (family, size_pt, weight_intent). iOS-side from AppSkin+BaseValues.
# iconTiny is a symbol glyph (no web font-family/size — only color matters), flagged.
FONT_ROLES = {
    "caption": {"family": "sans", "size": 12, "weight": "semibold"},   # AppFonts.sans(12,bold)
    "caption2": {"family": "sans", "size": 11, "weight": "regular"},
    "sectionTitle": {"family": "serif", "size": 18, "weight": "bold"},
    "body": {"family": "sans", "size": 17, "weight": "regular"},
    "monoLabel": {"family": "mono", "size": 10, "weight": "bold"},
    "iconTiny": {"glyph": True},  # SF Symbol — no text font props emitted
}
FONT_FAMILY_VAR = {"sans": "--font-sans", "serif": "--font-serif", "mono": "--font-mono"}

# appSkin.spacing.<field> measured px (web), from the parity rewrite. compactChip is
# MEASURED (5/10) not the raw iOS scalar (3/6) — a measured override, emitted as orphan.
SKIN_SPACING_PX = {
    "compactChipHorizontalPadding": (10, "orphan", "compactChip h measured 10 (iOS 6)"),
    "compactChipVerticalPadding": (5, "orphan", "compactChip v measured 5 (iOS 3)"),
    "chipHorizontalPadding": (10, "L2:pt_equals_px", "chip h 10"),
    "chipVerticalPadding": (6, "L2:pt_equals_px", "chip v 6"),
    "badgeHorizontalPadding": (9, "L2:pt_equals_px", "badge h 9"),
    "microGap": (6, "L2:pt_equals_px", "skin microGap 6"),
    "inlineGap": (8, "L1:token", "inlineGap 8"),
    "cardPadding": (18, "L1:token", "cardPadding 18"),
}
# symbolic metric constants (e.g. TodayReviewMetrics.chevronButtonSize) → px.
METRIC_PX = {"TodayReviewMetrics.chevronButtonSize": 30}

# L2 weight collapse: every iOS bold-ish weight → 700 (ElmsSans ships 400/700 only).
WEIGHT_700 = {"medium", "semibold", "bold"}


class Decl:
    __slots__ = ("prop", "value", "prov", "note")

    def __init__(self, prop, value, prov, note=""):
        self.prop, self.value, self.prov, self.note = prop, value, prov, note

    def render(self) -> str:
        tail = f"  /* {self.prov}{(': ' + self.note) if self.note else ''} */"
        return f"  {self.prop}: {self.value};{tail}"


# ---------------------------------------------------------------------------
# surface-container selection: pick the tree node whose decls map to the class
# ---------------------------------------------------------------------------

def pick_container(root: dict) -> dict:
    """Pick the node that represents the hand CSS class. Heuristic: descend through
    synthetic single-child wrappers (a `container` body root with one child and no own
    modifiers) until we reach the node that actually carries the surface's box
    (a stack, or a leaf/child painting a background/frame)."""
    node = root
    while (node["kind"] == "container" and len(node["children"]) == 1
           and not node["modifiers"]):
        node = node["children"][0]
    return node


def _is_leaf_wrapping_box(node: dict) -> bool:
    """A node that draws a background/capsule (or fixed frame) around inline content but is
    NOT itself a multi-axis stack → the SwiftUI 'label inside padding+background' idiom,
    which on web is an inline-flex centered wrapper (display:inline-flex; align-items &
    justify-content:center)."""
    if node["kind"] in ("HStack", "VStack", "ZStack"):
        return False
    has_bg = any(m["name"] == "background" for m in node["modifiers"])
    has_frame = any(m["name"] == "frame" for m in node["modifiers"])
    return has_bg or has_frame


# ---------------------------------------------------------------------------
# value resolvers (shared by v0; extended for skin_spacing / metric frame dims)
# ---------------------------------------------------------------------------

def _resolve_padding(edge: str, val: dict) -> list[Decl]:
    prop = {
        "all": "padding", "horizontal": "padding-inline", "vertical": "padding-block",
        "top": "padding-top", "bottom": "padding-bottom",
        "leading": "padding-inline-start", "trailing": "padding-inline-end",
    }.get(edge, "padding")

    if val["kind"] == "token":
        var = SP_VAR.get(val["token"])
        # only --sp-N aliases are folded by the evaluator; micro/tiny/hairline keep px
        px = SP_PX.get(val["token"])
        if var and var.startswith("--sp-") and var[5:].isdigit():
            return [Decl(prop, f"var({var})", "L1:token", val["token"])]
        if px is not None:
            return [Decl(prop, f"{px}px", "L2:pt_equals_px", val["token"])]
    if val["kind"] == "literal":
        return [Decl(prop, f"{val['value']}px", "L2:pt_equals_px", f"literal {val['value']}pt")]
    if val["kind"] == "skin_spacing":
        spec = SKIN_SPACING_PX.get(val["field"])
        if spec:
            px, prov, note = spec
            return [Decl(prop, f"{px}px", prov, note)]
    if val["kind"] == "expr":
        base = SP_PX.get(val["base"])
        addv = SP_PX.get(val["addend"])
        if addv is None and re.fullmatch(r"\d+", str(val["addend"])):
            addv = int(val["addend"])
        if base is not None and addv is not None:
            total = base + addv if val["op"] == "+" else base - addv
            note = f"{val['base']} {val['op']} {val['addend']} = {total}px (pt_equals_px)"
            return [Decl(prop, f"{total}px", "orphan", note)]
    return [Decl(prop, f"/* UNRESOLVED {val.get('raw')} */", "orphan", "padding unresolved")]


def _resolve_font(role: str, weight_override: str | None) -> list[Decl]:
    spec = FONT_ROLES.get(role)
    if not spec:
        return [Decl("font", f"/* UNKNOWN role {role} */", "orphan", "font role unmapped")]
    if spec.get("glyph"):
        return []  # SF Symbol glyph — no text font props on web
    fam_var = FONT_FAMILY_VAR[spec["family"]]
    out = [
        Decl("font-family", f"var({fam_var})", "L1:token", role),
        Decl("font-size", f"{spec['size']}px", "L1:token", f"{role}={spec['size']}px"),
    ]
    eff_weight = weight_override or spec["weight"]
    if eff_weight in WEIGHT_700:
        rule = "semibold_chip_700" if eff_weight == "semibold" else "bold_weight_700_floor"
        out.append(Decl("font-weight", "700", f"L2:{rule}", f"iOS .{eff_weight} → 700"))
    return out


def _dim_px(dv: dict) -> int | None:
    if dv["kind"] == "literal":
        return dv["value"]
    if dv["kind"] == "token":
        return SP_PX.get(dv["token"])
    if dv["kind"] == "metric":
        return METRIC_PX.get(dv["name"])
    return None


def _resolve_frame(dims: dict) -> list[Decl]:
    out = []
    for dim, dv in dims.items():
        px = _dim_px(dv)
        if px is None:
            continue
        prop = {"minWidth": "min-width", "width": "width",
                "height": "height", "minHeight": "min-height"}.get(dim, dim)
        out.append(Decl(prop, f"{px}px", "L2:pt_equals_px", f"frame {dim} {px}pt"))
    return out


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

def _emit_node_modifiers(node: dict, decls: list[Decl]) -> None:
    """Visual/geometry decls from a node's own modifier list. NOTE: for a frame with
    repeated dims (inner 34×18 then outer 48×30), the FIRST occurrence wins — it is the
    visual capsule the hand CSS targets; later frames are hit-target padding."""
    seen_frame_dims: set[str] = set()
    for m in node["modifiers"]:
        name = m["name"]
        if name == "padding":
            decls.extend(_resolve_padding(m["edge"], m["value"]))
        elif name == "font":
            decls.extend(_resolve_font(m["role"], m.get("weight_override")))
        elif name == "font_direct":
            fam_var = FONT_FAMILY_VAR.get(m["family"], "--font-sans")
            decls.append(Decl("font-family", f"var({fam_var})", "L1:token", m["family"]))
            decls.append(Decl("font-size", f"{m['size']}px", "L2:pt_equals_px", f"{m['size']}pt"))
            if m.get("bold"):
                decls.append(Decl("font-weight", "700", "L2:bold_weight_700_floor", "iOS bold → 700"))
        elif name == "foreground":
            var = COLOR_TOKENS.get(m["token"])
            if var:
                decls.append(Decl("color", f"var({var})", "L1:token", m["token"]))
            else:
                decls.append(Decl("color", f"/* param {m['token']} */", "orphan", "view-param color"))
        elif name == "frame":
            for d in _resolve_frame(m["dims"]):
                if d.prop in seen_frame_dims:
                    continue  # first frame (visual box) wins over outer hit-target frame
                seen_frame_dims.add(d.prop)
                decls.append(d)
        elif name == "spacer":
            decls.append(Decl("flex", "1", "L1:token", "Spacer"))
        elif name == "background":
            tok = m.get("token")
            var = COLOR_TOKENS.get(tok)
            if var:
                if m.get("opacity") is not None:
                    val = f"color-mix(in srgb, var({var}) {round(m['opacity']*100)}%, transparent)"
                    decls.append(Decl("background", val, "L1:token", f"{tok}.opacity({m['opacity']})"))
                else:
                    decls.append(Decl("background", f"var({var})", "L1:token", tok))
            elif tok:
                decls.append(Decl("background", f"/* param {tok} */", "orphan", "view-param fill"))
            shape = m.get("shape")
            if shape == "capsule":
                decls.append(Decl("border-radius", "var(--radius-pill)", "L1:token", "Capsule"))
            elif m.get("radius"):
                rvar = RADIUS_VAR.get(m["radius"])
                if rvar:
                    decls.append(Decl("border-radius", f"var({rvar})", "L1:token", m["radius"]))
        elif name == "stroke":
            var = COLOR_TOKENS.get(m["token"], "--divider")
            lw = m.get("line_width", "1")
            lw_px = SP_PX.get(lw, lw)  # AppSpacing.hairline → 1
            if m.get("opacity") is not None:
                color = f"color-mix(in srgb, var({var}) {round(m['opacity']*100)}%, transparent)"
            else:
                color = f"var({var})"
            decls.append(Decl("border", f"{lw_px}px solid {color}", "L2:pt_equals_px",
                              f"stroke {m['token']} lineWidth {lw}"))


def _paints_capsule(node: dict) -> bool:
    return any(m["name"] == "background" and m.get("shape") == "capsule"
               for m in node["modifiers"])


def _emit_layout(container: dict, decls: list[Decl]) -> None:
    """The v1 unlock: structural flex declarations from the node's nature."""
    kind = container["kind"]
    if kind in ("HStack", "VStack", "ZStack"):
        # a stack painting a Capsule is a pill → inline-flex (sits inline in its row);
        # a plain layout stack is block-level flex.
        disp = "inline-flex" if _paints_capsule(container) else "flex"
        decls.append(Decl("display", disp, "L1:layout", kind))
        decls.append(Decl("flex-direction",
                          "row" if kind == "HStack" else "column",
                          "L1:layout", kind))
        # HStack default vertical-center; VStack default horizontal-leading
        decls.append(Decl("align-items",
                          "center" if kind == "HStack" else "stretch",
                          "L1:layout", f"{kind} cross-axis default"))
        sp = container.get("spacing")
        if sp and sp.get("kind") == "token":
            var = SP_VAR.get(sp["token"])
            if var:
                decls.append(Decl("gap", f"var({var})", "L1:layout", f"spacing {sp['token']}"))
        # a Spacer child means the row distributes — justify space-between
        if any(c["kind"] == "Spacer" for c in container.get("children", [])):
            decls.append(Decl("justify-content", "space-between", "L1:layout", "Spacer present"))
    elif _is_leaf_wrapping_box(container):
        # label-inside-padding+background idiom → inline-flex centered wrapper
        decls.append(Decl("display", "inline-flex", "L1:layout", "leaf-wrapping box"))
        decls.append(Decl("align-items", "center", "L1:layout", "centered wrapper"))
        decls.append(Decl("justify-content", "center", "L1:layout", "centered wrapper"))


def emit_css(struct: dict, selector: str) -> tuple[str, dict]:
    root = struct["root"]
    container = pick_container(root)
    decls: list[Decl] = []

    _emit_layout(container, decls)
    _emit_node_modifiers(container, decls)

    stats = {"L1": 0, "L2": 0, "orphan": 0, "unmapped": 0}
    for d in decls:
        cls = d.prov.split(":")[0] if ":" in d.prov else d.prov
        if cls == "L1":
            stats["L1"] += 1
        elif cls == "L2":
            stats["L2"] += 1
        else:
            stats["orphan"] += 1
    # collect unparsed from the container and its synthetic ancestors
    unparsed = list(container.get("unparsed", []))
    stats["unmapped"] = len(unparsed)

    body = "\n".join(d.render() for d in decls)
    css = f"/* engine-generated from {struct['name']} (L1 token · L2 codex · v1 tree) */\n.{selector} {{\n{body}\n"
    if unparsed:
        css += "  /* UNPARSED (extractor could not classify): */\n"
        for u in unparsed:
            css += f"  /*   {u} */\n"
    css += "}\n"
    return css, stats


def main(argv: list[str]) -> int:
    pos = [a for a in argv[1:] if not a.startswith("--")]
    opts = {}
    for k, a in enumerate(argv):
        if a.startswith("--") and k + 1 < len(argv):
            opts[a[2:]] = argv[k + 1]
    if not pos:
        print("usage: generate_css.py <ir.json> --selector <class> [--struct Name] [--out f.css]",
              file=sys.stderr)
        return 2
    ir = json.loads(Path(pos[0]).read_text(encoding="utf-8"))
    structs = ir["structs"]
    if "struct" in opts:
        structs = [s for s in structs if s["name"] == opts["struct"]]
    if not structs:
        print("no matching struct", file=sys.stderr)
        return 1
    selector = opts.get("selector", "engine-block")
    css, stats = emit_css(structs[0], selector)
    if "out" in opts:
        Path(opts["out"]).write_text(css, encoding="utf-8")
        print(f"wrote {opts['out']}", file=sys.stderr)
    else:
        print(css)
    print(f"# stats: L1={stats['L1']} L2={stats['L2']} orphan={stats['orphan']} "
          f"unmapped={stats['unmapped']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
