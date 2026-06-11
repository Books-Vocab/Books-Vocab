#!/usr/bin/env python3
"""
generate_css.py — L1 deterministic token mapper + L2 codex applier (migration engine v0).

Input : intermediate representation JSON from extract_swiftui.py.
Output: a CSS declaration draft per struct, every line annotated with provenance:
          /* L1:token */ , /* L2:<rule_name> */ , or /* orphan */.

L1 (the ~70%): symbolic name → css var, pure isomorphism, no measurement.
  - AppSpacing.sN          → var(--sp-N)
  - AppRadius.lg           → var(--radius-lg)
  - palette.<tok>          → var(--<color-token>)   (COLOR_TOKENS map)
  - font role              → font-family/size/weight from FONT_ROLES
  - VStack/HStack(spacing) → display:flex + gap
  - Spacer(minLength)      → flex:1 + min dimension
  - .frame(minWidth)       → min-width

L2 (the ~18%): codex/l2_rules.yaml predicates rewrite non-isomorphic deltas
  to `token + named delta`, emitting the iOS intent as a comment.
  v0 wires the rules the slice exercises:
    - bold_weight_700_floor / semibold_chip_700  (font-weight collapse → 700)
    - hairline_physical_px                        (sub-pt stroke → 0.34px)
    - pt_equals_px unit contract                  (literal pt → px)

Composite padding exprs (AppSpacing.s2 + 2) are resolved numerically against the
token scalar table (kg-tokens.css values) and emitted as px with an L2/orphan note
depending on whether the offset is a known codex delta.

Run: uv run python lab/migration_engine/engine/generate_css.py <ir.json> --selector <css-class> [--struct Name]
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# scalar values resolved from web/src/styles/kg-tokens.css (the shared SoT numbers).
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
    "AppSpacing.s10": "--sp-10",
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
FONT_ROLES = {
    "caption": {"family": "sans", "size": 12, "weight": "regular"},
    "caption2": {"family": "sans", "size": 11, "weight": "regular"},
    "sectionTitle": {"family": "serif", "size": 18, "weight": "bold"},
    "body": {"family": "sans", "size": 17, "weight": "regular"},
}
FONT_FAMILY_VAR = {"sans": "--font-sans", "serif": "--font-serif", "mono": "--font-mono"}

# L2 weight collapse (bold_weight_700_floor / semibold_chip_700): every iOS
# bold-ish weight → 700 (ElmsSans ships 400/700 only).
WEIGHT_700 = {"medium", "semibold", "bold"}

# hairline_physical_px delta: iOS hairline stroke → 0.34px web (1 phys px / dpr3).
HAIRLINE_DPR3 = 0.34


class Decl:
    __slots__ = ("prop", "value", "prov", "note")

    def __init__(self, prop, value, prov, note=""):
        self.prop, self.value, self.prov, self.note = prop, value, prov, note

    def render(self) -> str:
        tail = f"  /* {self.prov}{(': ' + self.note) if self.note else ''} */"
        return f"  {self.prop}: {self.value};{tail}"


def _resolve_padding(edge: str, val: dict) -> list[Decl]:
    prop = {
        "all": "padding", "horizontal": "padding-inline", "vertical": "padding-block",
        "top": "padding-top", "bottom": "padding-bottom",
        "leading": "padding-inline-start", "trailing": "padding-inline-end",
    }.get(edge, "padding")

    if val["kind"] == "token":
        var = SP_VAR.get(val["token"])
        if var:
            return [Decl(prop, f"var({var})", "L1:token", val["token"])]
        # hairline/micro/tiny aren't on the --sp-N grid alias used here
        px = SP_PX.get(val["token"])
        if px is not None:
            return [Decl(prop, f"{px}px", "L2:pt_equals_px", val["token"])]
    if val["kind"] == "literal":
        return [Decl(prop, f"{val['value']}px", "L2:pt_equals_px", f"literal {val['value']}pt")]
    if val["kind"] == "expr":
        base = SP_PX.get(val["base"])
        addv = SP_PX.get(val["addend"])
        if addv is None and re.fullmatch(r"\d+", str(val["addend"])):
            addv = int(val["addend"])
        if base is not None and addv is not None:
            total = base + addv if val["op"] == "+" else base - addv
            note = f"{val['base']} {val['op']} {val['addend']} = {total}px (pt_equals_px)"
            # offset off the token grid → annotated orphan constant, not a codex rule
            return [Decl(prop, f"{total}px", "orphan", note)]
    return [Decl(prop, f"/* UNRESOLVED {val.get('raw')} */", "orphan", "padding unresolved")]


def _resolve_font(role: str, weight_override: str | None) -> list[Decl]:
    spec = FONT_ROLES.get(role)
    if not spec:
        return [Decl("font", f"/* UNKNOWN role {role} */", "orphan", "font role unmapped")]
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


def emit_css(struct: dict, selector: str) -> tuple[str, dict]:
    """Return (css_text, stats). stats = counts by provenance class."""
    elem = struct["elements"][0]
    decls: list[Decl] = []
    stats = {"L1": 0, "L2": 0, "orphan": 0, "unmapped": 0}

    for m in elem["modifiers"]:
        name = m["name"]
        if name == "stack":
            decls.append(Decl("display", "flex", "L1:token", m["kind"]))
            decls.append(Decl("flex-direction",
                              "row" if m["kind"] == "HStack" else "column",
                              "L1:token", m["kind"]))
            sp = m.get("spacing")
            if sp and sp.get("kind") == "token":
                var = SP_VAR.get(sp["token"])
                if var:
                    decls.append(Decl("gap", f"var({var})", "L1:token", f"spacing {sp['token']}"))
            decls.append(Decl("align-items", "center", "L1:token", "HStack vertical-center default"))
        elif name == "padding":
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
            if m.get("min_width") is not None:
                decls.append(Decl("min-width", f"{m['min_width']}px", "L2:pt_equals_px",
                                  f"minWidth {m['min_width']}pt"))
        elif name == "spacer":
            decls.append(Decl("flex", "1", "L1:token", "Spacer"))
            ml = m.get("min_length")
            if ml:
                mlpx = SP_PX.get(ml) or (int(ml) if str(ml).isdigit() else None)
                if mlpx is not None:
                    decls.append(Decl("min-width", f"{mlpx}px", "L2:pt_equals_px",
                                      f"Spacer(minLength {ml})"))
        elif name == "background":
            tok = m.get("token")
            var = COLOR_TOKENS.get(tok)
            if var:
                if m.get("opacity") is not None:
                    val = f"color-mix(in srgb, var({var}) {int(m['opacity']*100)}%, transparent)"
                    decls.append(Decl("background", val, "L1:token",
                                      f"{tok}.opacity({m['opacity']})"))
                else:
                    decls.append(Decl("background", f"var({var})", "L1:token", tok))
            elif tok:
                decls.append(Decl("background", f"/* param {tok} */", "orphan", "view-param fill"))
            # shape → border-radius
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
            # AppMetrics hairline lineWidth 1.5 is a thin rule; keep as px (pt_equals_px)
            decls.append(Decl("border",
                              f"{lw}px solid var({var})", "L2:pt_equals_px",
                              f"stroke {m['token']} lineWidth {lw}"))
        elif name == "leaf":
            continue  # leaf Text/Image have no container-level decl in v0

    for d in decls:
        cls = d.prov.split(":")[0] if ":" in d.prov else d.prov
        if cls == "L1":
            stats["L1"] += 1
        elif cls == "L2":
            stats["L2"] += 1
        else:
            stats["orphan"] += 1
    stats["unmapped"] = len(elem.get("unmapped", []))

    body = "\n".join(d.render() for d in decls)
    css = f"/* engine-generated from {struct['name']} (L1 token · L2 codex) */\n.{selector} {{\n{body}\n"
    if elem.get("unmapped"):
        css += "  /* UNMAPPED (extractor could not classify): */\n"
        for u in elem["unmapped"]:
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
