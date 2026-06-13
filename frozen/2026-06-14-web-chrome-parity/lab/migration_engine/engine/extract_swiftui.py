#!/usr/bin/env python3
"""
extract_swiftui.py — SwiftUI extractor (migration engine v1: child-tree IR).

v0 collapsed a `View` body into ONE flat modifier list — enough for container-level
declarations, but structurally blind: it could not see that a pill wraps its label in
an `HStack`, so it never emitted the `display:inline-flex; align-items:center;
justify-content:center; gap` that EVERY chip/row needs. That single flat-IR limitation
was v0's measured top miss (V0_REPORT.md §1).

v1 builds a **nested tree**. The body is parsed into container nodes (VStack / HStack /
ZStack) and leaf nodes (Text / Image / Spacer / child-view calls), each carrying its own
modifier list. A modifier chain attaches to the node it decorates. The heuristic is still
indentation + balanced parens — NOT a Swift AST parser — and any subtree it cannot classify
is emitted as a `unparsed` node so the downstream report counts the degrade honestly.

IR shape (per struct):
  { "name", "root": <node> }
  node = { "kind": "VStack|HStack|ZStack|Text|Image|Spacer|child|container|unparsed",
           "selector_hint": str|None,
           "axis": "row|column|stack"|None,        # for stacks (HStack=row, VStack=column)
           "spacing": <padding-val>|None,           # stack child spacing
           "modifiers": [ {modifier record} ],
           "children": [ <node>, ... ],
           "unparsed": [ raw-line, ... ] }

A modifier record is the same vocabulary v0 used (padding / font / foreground / frame /
background / stroke), now attached per-node instead of flattened to the root.

Run: uv run python lab/migration_engine/engine/extract_swiftui.py <view.swift> [--struct Name] [--out f.json]
"""
from __future__ import annotations
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --- token-scalar identity sets (numbers resolved in generate_css.py) ----------

SPACING_TOKENS = {
    "AppSpacing.hairline", "AppSpacing.microGap", "AppSpacing.tinyGap",
    "AppSpacing.s1", "AppSpacing.s2", "AppSpacing.s3", "AppSpacing.s4",
    "AppSpacing.s5", "AppSpacing.s6", "AppSpacing.s7", "AppSpacing.s8",
    "AppSpacing.s9", "AppSpacing.s10",
}


@dataclass
class Node:
    kind: str
    selector_hint: str | None = None
    axis: str | None = None
    spacing: dict | None = None
    modifiers: list[dict] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


# --- regex vocabulary (per-line modifier recognition) ------------------------

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
RE_FRAME_DIM = re.compile(r"(?P<dim>minWidth|width|height|minHeight):\s*(?P<v>[A-Za-z0-9_.]+)")
RE_RRECT = re.compile(r"RoundedRectangle\(cornerRadius:\s*(?P<r>[^,)]+)")
RE_FILL = re.compile(r"\.fill\(\s*(?:skin|appSkin)\.palette\.(?P<tok>\w+)(?P<chain>[^)]*)\)")
RE_STROKE = re.compile(r"\.stroke\(\s*(?:skin|appSkin)\.palette\.(?P<tok>\w+)[^,]*,\s*lineWidth:\s*(?P<lw>[^)]+)\)")
RE_TEXT = re.compile(r"\bText\(")
RE_IMAGE = re.compile(r"\bImage\(systemName:")
# A child-view call: CapitalizedIdentifier(  — used to detect composed sub-components.
RE_CHILD_CALL = re.compile(r"\b(?P<name>[A-Z]\w+)\s*\(")
# Known non-view capitalized calls to ignore as "child views".
_NOT_A_VIEW = {
    "Text", "Image", "Spacer", "RoundedRectangle", "Capsule", "Circle",
    "Rectangle", "Color", "Label", "Button", "Menu", "Divider", "ForEach",
    "AppColors", "AppSpacing", "AppRadius", "AppFonts", "L10n", "VStack",
    "HStack", "ZStack",
}

_SPACING_FIELDS = {  # appSkin.spacing.<field> → symbolic name the generator resolves
    "compactChipHorizontalPadding", "compactChipVerticalPadding",
    "chipHorizontalPadding", "chipVerticalPadding", "chipVerticalPaddingLoose",
    "badgeHorizontalPadding", "microGap", "inlineGap", "cardPadding",
}


def _join_chained_modifiers(lines: list[str]) -> list[str]:
    """Collapse a modifier whose argument spans multiple lines (balanced parens) into
    one logical line, e.g. `.background(\\n RoundedRectangle(...).fill(...) \\n )`. Brace
    depth (`{`/`}`) is preserved on the joined line so the tree builder's depth tracking
    stays correct. Heuristic: when a stripped line ends on an unbalanced '(' opened by a
    `.background(` / `.overlay(` / `.frame(` / `.font(` / `.fill(` / `.stroke(`, keep
    consuming until parens rebalance."""
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
        # only fold pure modifier-argument continuations that carry NO braces (so we never
        # swallow a stack's `{` opener into a joined line and corrupt depth tracking).
        if bal > 0 and "{" not in s and "}" not in s and any(t in s for t in triggers):
            buf = s
            depth = bal
        else:
            out.append(s)
    if buf:
        out.append(buf)
    return out


def _parse_dim_val(raw: str) -> dict:
    raw = raw.strip()
    if raw in SPACING_TOKENS:
        return {"kind": "token", "token": raw, "raw": raw}
    if re.fullmatch(r"\d+", raw):
        return {"kind": "literal", "value": int(raw), "raw": raw}
    # symbolic metric constant (e.g. TodayReviewMetrics.chevronButtonSize) — generator
    # resolves via a small metric table; carry the dotted name.
    if re.fullmatch(r"[A-Za-z_]\w*\.\w+", raw):
        return {"kind": "metric", "name": raw, "raw": raw}
    return {"kind": "unknown", "raw": raw}


def _parse_padding_val(val: str) -> dict:
    """Return {kind, ...}. Handles token / AppSpacing.sN±k / literal / skin.spacing field."""
    val = val.strip()
    if val in SPACING_TOKENS:
        return {"kind": "token", "token": val, "raw": val}
    m = re.match(r"(AppSpacing\.\w+)\s*([+\-])\s*(AppSpacing\.\w+|\d+)", val)
    if m:
        return {"kind": "expr", "base": m.group(1), "op": m.group(2),
                "addend": m.group(3), "raw": val}
    m = re.match(r"(?:appSkin|skin)\.spacing\.(?P<f>\w+)", val)
    if m and m.group("f") in _SPACING_FIELDS:
        return {"kind": "skin_spacing", "field": m.group("f"), "raw": val}
    if re.fullmatch(r"\d+", val):
        return {"kind": "literal", "value": int(val), "raw": val}
    return {"kind": "unknown", "raw": val}


def _attach_modifiers(node: Node, s: str, joined: str) -> bool:
    """Recognize every modifier on stripped line `s` and append to node. Returns True
    if any known modifier (or stack/leaf marker) was recognized."""
    matched = False

    for m in RE_PADDING.finditer(s):
        edge = m.group("edge") or "all"
        pv = _parse_padding_val(m.group("val"))
        node.modifiers.append({"name": "padding", "edge": edge, "value": pv, "raw": s})
        matched = True

    m = RE_FONT.search(s)
    if m:
        chain = m.group("chain") or ""
        wm = re.search(r"\.weight\(\.(\w+)\)", chain)
        node.modifiers.append({"name": "font", "role": m.group("role"),
                               "weight_override": wm.group(1) if wm else None, "raw": s})
        matched = True
    m = RE_FONT_DIRECT.search(s)
    if m:
        node.modifiers.append({"name": "font_direct", "family": m.group("fn"),
                               "size": int(m.group("size")),
                               "bold": m.group("bold") == "true", "raw": s})
        matched = True

    for rgx in (RE_FG, RE_FG2):
        m = rgx.search(s)
        if m:
            node.modifiers.append({"name": "foreground", "token": m.group("tok"), "raw": s})
            matched = True

    m = RE_FRAME.search(s)
    if m:
        args = m.group("args")
        dims = {dm.group("dim"): _parse_dim_val(dm.group("v"))
                for dm in RE_FRAME_DIM.finditer(args)}
        if dims:
            node.modifiers.append({"name": "frame", "dims": dims, "raw": s})
            matched = True

    for m in RE_FILL.finditer(s):
        om = re.search(r"\.fill\([^)]*\.opacity\(([\d.]+)\)", s)
        opacity = float(om.group(1)) if om else None
        shape = "capsule" if "Capsule" in s else ("rrect" if "RoundedRectangle" in joined else "shape")
        rm = RE_RRECT.search(s)
        node.modifiers.append({"name": "background", "token": m.group("tok"),
                               "opacity": opacity, "shape": shape,
                               "radius": rm.group("r").strip() if rm else None, "raw": s})
        matched = True
    if "Capsule(style: .continuous).fill(" in s and not RE_FILL.search(s):
        fm = re.search(r"\.fill\((\w+)\)", s)
        node.modifiers.append({"name": "background", "token": fm.group(1) if fm else None,
                               "opacity": None, "shape": "capsule", "radius": None,
                               "param": True, "raw": s})
        matched = True

    m = RE_STROKE.search(s)
    if m:
        om = re.search(r"\.stroke\(\s*(?:skin|appSkin)\.palette\.\w+\.opacity\(([\d.]+)\)", s)
        node.modifiers.append({"name": "stroke", "token": m.group("tok"),
                               "opacity": float(om.group(1)) if om else None,
                               "line_width": m.group("lw").strip(), "raw": s})
        matched = True

    return matched


def _build_tree(body_lines: list[str]) -> Node:
    """Parse a SwiftUI body into a nested container/leaf tree.

    Heuristic state machine over brace depth:
      - `HStack/VStack/ZStack(...) {` opens a container node, pushed on a stack keyed by
        the brace depth at which its `{` opened.
      - a leaf (`Text(`, `Image(systemName:`, `Spacer(`, or a child-view call) becomes a
        leaf node appended to the current container.
      - a modifier line (starts with `.`) attaches to the *last view node opened at or below
        the current depth* (the SwiftUI rule: a chain decorates the preceding view).
    Unrecognized view-ish constructs are kept as `unparsed` on the nearest container.
    """
    body_lines = _join_chained_modifiers(body_lines)
    joined = "\n".join(body_lines)
    root = Node(kind="container")
    # container stack: list of (open_depth, node). root holds depth -1.
    stack: list[tuple[int, Node]] = [(-1, root)]
    last_view: Node | None = None  # most recent view node, for modifier attachment
    depth = 0

    for raw in body_lines:
        s = raw.strip()
        opens = raw.count("{")
        closes = raw.count("}")

        if not s or s.startswith("//"):
            depth += opens - closes
            continue

        cur_container = stack[-1][1]

        # close containers whose block ended
        # (handled after content parse so a same-line close still sees its content)

        handled = False

        # --- container: stack opener ---
        sm = RE_STACK.search(s)
        if sm and "{" in s:
            sp = sm.group("sp")
            kind = sm.group("kind")
            cnode = Node(kind=kind,
                         axis="row" if kind == "HStack" else ("column" if kind == "VStack" else "stack"),
                         spacing=_parse_padding_val(sp) if sp else None)
            cur_container.children.append(cnode)
            stack.append((depth, cnode))
            last_view = cnode
            handled = True

        # --- leaf views ---
        if not handled:
            if RE_TEXT.search(s):
                leaf = Node(kind="Text")
                cur_container.children.append(leaf)
                last_view = leaf
                _attach_modifiers(leaf, s, joined)
                handled = True
            elif RE_IMAGE.search(s):
                leaf = Node(kind="Image")
                cur_container.children.append(leaf)
                last_view = leaf
                _attach_modifiers(leaf, s, joined)
                handled = True
            elif RE_SPACER.search(s):
                m = RE_SPACER.search(s)
                leaf = Node(kind="Spacer")
                leaf.modifiers.append({"name": "spacer",
                                       "min_length": (m.group("ml") or "").strip() or None, "raw": s})
                cur_container.children.append(leaf)
                last_view = leaf
                handled = True

        # --- child-view call (composed sub-component) ---
        if not handled:
            cm = RE_CHILD_CALL.search(s)
            if cm and cm.group("name") not in _NOT_A_VIEW and not s.startswith("."):
                leaf = Node(kind="child", selector_hint=cm.group("name"))
                cur_container.children.append(leaf)
                last_view = leaf
                handled = True

        # --- modifier line: attach to last view ---
        if not handled and s.startswith("."):
            target = last_view if last_view is not None else cur_container
            if _attach_modifiers(target, s, joined):
                handled = True
            elif any(t in s for t in (".padding", ".font", ".frame", ".background",
                                      ".overlay", ".foreground", ".fill", ".stroke")):
                target.unparsed.append(s)
                handled = True

        # --- inline modifiers on a same-line view (e.g. `Text("x").font(...)`) ---
        if handled and last_view is not None and not s.startswith("."):
            # the line opened/created a view AND may carry trailing modifiers
            _attach_modifiers(last_view, s, joined)

        # --- catch unmapped view-ish constructs ---
        if not handled and any(tok in s for tok in (
                ".padding", ".font", ".frame", ".background", ".overlay",
                ".foreground", "RoundedRectangle", "Capsule")):
            cur_container.unparsed.append(s)

        # update depth and pop closed containers. A modifier chain that follows a
        # container's closing `}` decorates THAT container (SwiftUI: `HStack { … }.padding()`),
        # so point last_view at the just-popped container for the next line's attachment.
        depth += opens - closes
        while len(stack) > 1 and depth <= stack[-1][0]:
            _, popped = stack.pop()
            last_view = popped

    return root


def extract_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    structs = []
    i = 0
    while i < len(lines):
        m = re.match(r"\s*struct\s+(\w+)(?:<[^>]+>)?\s*:\s*View\b", lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
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
        # drop the `var body ... {` opener and the trailing `}` so _build_tree sees body content
        inner = body_lines[1:-1] if len(body_lines) >= 2 else body_lines
        root = _build_tree(inner)
        structs.append({"name": name, "root": asdict(root)})
        i = j + 1
    return {"source": str(path), "structs": structs}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    out = struct_filter = None
    for k, a in enumerate(argv):
        if a == "--out" and k + 1 < len(argv):
            out = argv[k + 1]
        if a == "--struct" and k + 1 < len(argv):
            struct_filter = argv[k + 1]
    if not args:
        print("usage: extract_swiftui.py <view.swift> [--struct Name] [--out f.json]", file=sys.stderr)
        return 2
    ir = extract_file(Path(args[0]))
    if struct_filter:
        ir["structs"] = [s for s in ir["structs"] if s["name"] == struct_filter]
    payload = json.dumps(ir, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(payload, encoding="utf-8")
        print(f"wrote {out} ({len(ir['structs'])} struct(s))", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
