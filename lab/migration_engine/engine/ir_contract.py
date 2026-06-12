#!/usr/bin/env python3
"""
ir_contract.py — the box-tree IR seam contract.

This is the load-bearing interface between the FRONT-END (a parser: today the regex
heuristic `extract_swiftui.py`, tomorrow the SwiftSyntax AST dumper) and the BACK-END
(`generate_css.py` L1 token + L2 codex applier, and the L2 codex itself).

Any parser that emits IR passing `validate_ir()` is guaranteed to be consumable by
generate_css without a structural surprise. So when we swap the regex parser for the
AST dumper, this contract is the red light the new parser must turn green — not the
pixel RMSE (that comes after), the *shape* first.

The schema is reverse-derived from what generate_css.py actually reads, so "passes
contract" ⟺ "generator can consume it". Keep this file the single source of the seam.
"""
from __future__ import annotations

# --- the seam vocabulary (must stay in lockstep with generate_css.py) ----------

NODE_KINDS = {
    "container", "HStack", "VStack", "ZStack",
    "Text", "Image", "Spacer", "child", "unparsed",
}
MODIFIER_NAMES = {
    "padding", "font", "font_direct", "foreground",
    "frame", "spacer", "background", "stroke",
}
# "unknown" is the value-level degrade marker (parser gave up on this scalar; the
# generator skips it / emits an orphan). It is the scalar analogue of the node-level
# "unparsed" kind, so the contract admits it — but the AST dumper's goal is to drive
# both toward zero.
VALUE_KINDS = {"token", "literal", "skin_spacing", "expr", "metric", "unknown"}
PADDING_EDGES = {
    "all", "horizontal", "vertical", "top", "bottom", "leading", "trailing",
}

# per-modifier required fields (only what generate_css dereferences unconditionally).
_MOD_REQUIRED = {
    "padding": ("edge", "value"),
    "font": ("role",),
    "font_direct": ("family", "size"),
    "foreground": ("token",),
    "frame": ("dims",),
    "spacer": (),
    "background": (),          # token/shape/radius/opacity all optional (param fills exist)
    "stroke": ("token",),
}
_VALUE_REQUIRED = {
    "token": ("token",),
    "literal": ("value",),
    "skin_spacing": ("field",),
    "expr": ("base", "op", "addend"),
    "metric": ("name",),
    "unknown": (),
}


def _err(path: str, msg: str) -> str:
    return f"{path}: {msg}"


def _validate_value(val: dict, path: str, errors: list[str]) -> None:
    if not isinstance(val, dict):
        errors.append(_err(path, f"value must be object, got {type(val).__name__}"))
        return
    kind = val.get("kind")
    if kind not in VALUE_KINDS:
        errors.append(_err(path, f"value.kind {kind!r} not in {sorted(VALUE_KINDS)}"))
        return
    for f in _VALUE_REQUIRED[kind]:
        if f not in val:
            errors.append(_err(path, f"value(kind={kind}) missing required field {f!r}"))


def _validate_modifier(mod: dict, path: str, errors: list[str]) -> None:
    if not isinstance(mod, dict):
        errors.append(_err(path, f"modifier must be object, got {type(mod).__name__}"))
        return
    name = mod.get("name")
    if name not in MODIFIER_NAMES:
        errors.append(_err(path, f"modifier.name {name!r} not in {sorted(MODIFIER_NAMES)}"))
        return
    for f in _MOD_REQUIRED[name]:
        if f not in mod:
            errors.append(_err(path, f"modifier({name}) missing required field {f!r}"))
    # deep checks on fields the generator dereferences as nested objects
    if name == "padding":
        if mod.get("edge") not in PADDING_EDGES:
            errors.append(_err(path, f"padding.edge {mod.get('edge')!r} not in {sorted(PADDING_EDGES)}"))
        if "value" in mod:
            _validate_value(mod["value"], f"{path}.value", errors)
    if name == "frame":
        dims = mod.get("dims")
        if not isinstance(dims, dict):
            errors.append(_err(path, "frame.dims must be object"))
        else:
            for dname, dval in dims.items():
                _validate_value(dval, f"{path}.dims.{dname}", errors)


def _validate_node(node: dict, path: str, errors: list[str]) -> None:
    if not isinstance(node, dict):
        errors.append(_err(path, f"node must be object, got {type(node).__name__}"))
        return
    kind = node.get("kind")
    if kind not in NODE_KINDS:
        errors.append(_err(path, f"node.kind {kind!r} not in {sorted(NODE_KINDS)}"))
    # structural fields the generator iterates unconditionally
    for f, ty in (("modifiers", list), ("children", list), ("unparsed", list)):
        if not isinstance(node.get(f), ty):
            errors.append(_err(path, f"node.{f} must be {ty.__name__}, got {type(node.get(f)).__name__}"))
    sp = node.get("spacing")
    if sp is not None:
        _validate_value(sp, f"{path}.spacing", errors)
    for i, m in enumerate(node.get("modifiers", []) or []):
        _validate_modifier(m, f"{path}.modifiers[{i}]", errors)
    for i, c in enumerate(node.get("children", []) or []):
        _validate_node(c, f"{path}.children[{i}]", errors)


def validate_ir(ir: dict) -> list[str]:
    """Return a list of contract violations; empty list == valid IR.

    A parser whose output validates here is guaranteed structurally consumable by
    generate_css.py — that is the contract.
    """
    errors: list[str] = []
    if not isinstance(ir, dict):
        return [_err("$", f"IR root must be object, got {type(ir).__name__}")]
    structs = ir.get("structs")
    if not isinstance(structs, list):
        return [_err("$.structs", "must be a list")]
    for i, s in enumerate(structs):
        p = f"$.structs[{i}]"
        if not isinstance(s, dict):
            errors.append(_err(p, "struct must be object"))
            continue
        if not isinstance(s.get("name"), str):
            errors.append(_err(p, "struct.name must be str"))
        if "root" not in s:
            errors.append(_err(p, "struct missing 'root'"))
        else:
            _validate_node(s["root"], f"{p}.root", errors)
    return errors
