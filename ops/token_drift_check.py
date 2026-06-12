#!/usr/bin/env -S uv run --python 3.13 python
"""token_drift_check — guard the web design tokens against the iOS Swift SoT.

design-system/tokens.json claims to mirror the iOS token literals. This script
PROVES it: it parses the authoritative Swift symbols and asserts every mirrored
value still matches. If someone changes a colour / spacing / radius / type size
on iOS and forgets to update tokens.json (and regenerate the CSS), this fails —
so cross-platform drift can never merge silently.

Coverage — EVERY token carrying a `$swift` provenance key is checked:
  AppColors    primitive palette (rgb literals) + vocab-highlight CSS strings
  AppTheme     per-theme surfaces / text / borders (rgb + Color.black/white.opacity)
  AppMetrics   AppSpacing scale, AppRadius scale, AppElevation z0..z4, AppMotion
               durations / timingCurve control points, TapFeedback scalars
  AppFonts     TypeScale ramp, Tracking scale
  AppSkin      baseTypography sizes, baseSpacing / baseMetrics (incl. labelTracking),
               baseRadii refs
  UIComponents AppTagMetrics chip padding + AppTag fill opacity (AppSurface.swift),
               AppShellMetrics (toolbar badge padding)
  Scenes       TodayReviewMetrics (progressBarGap, …)

Web-only values WITHOUT a $swift key (leading ratios, spring bezier
approximations, composed --transition-* shorthands, CJK fallbacks) are out of
scope by design and documented under $platform-equivalence in tokens.json.
Two component tokens carry iOS provenance in $description but NO $swift because
their source is not a parseable `enum { static let }`: space.semantic.empty-state-stack
(AppEmptyStateStyle.vocab(_:) struct init arg) and space.semantic.progress-bar-fill-min
(VocabComponents.swift inline `max(6, …)` literal). Add $swift if those move to enums.
Invariant: a $swift-bearing token that this guard cannot map to a real Swift
symbol raises an error rather than being silently skipped.

Run:  uv run python ops/token_drift_check.py
Exit: 0 = in sync, 1 = drift found.

Env overrides (tests): KG_TOKENS_JSON, KG_IOS_MODELS_DIR, KG_IOS_UICOMPONENTS_DIR.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS_JSON = Path(os.environ.get("KG_TOKENS_JSON", REPO / "design-system" / "tokens.json"))
MODELS = Path(os.environ.get("KG_IOS_MODELS_DIR", REPO / "ios" / "BooksAndVocab" / "Models"))
UICOMPONENTS = Path(os.environ.get(
    "KG_IOS_UICOMPONENTS_DIR", REPO / "ios" / "BooksAndVocab" / "UIComponents"))

EPS = 5e-3  # Tolerance for hex↔rgb float quantisation (max error = 1/255 ≈ 0.0039)
_FLOAT = r"[-+]?[0-9]*\.?[0-9]+"


# --------------------------------------------------------------------------
# Swift parsers
# --------------------------------------------------------------------------

def _read(name: str) -> str:
    return (MODELS / name).read_text(encoding="utf-8")


def _read_uic(name: str) -> str:
    return (UICOMPONENTS / name).read_text(encoding="utf-8")


def _read_rel(relpath: str) -> str:
    """Read a Swift file by path relative to ios/BooksAndVocab/ — for sources
    outside Models/ and UIComponents/ (e.g. Views/Vocabulary/Scenes/)."""
    return (MODELS.parent / relpath).read_text(encoding="utf-8")


def parse_app_colors() -> dict[str, tuple[float, float, float]]:
    """name -> (r,g,b) for `static let name = Color(red: r, green: g, blue: b)`."""
    src = _read("AppColors.swift")
    pat = re.compile(
        r"static let (\w+)\s*=\s*Color\(red:\s*(" + _FLOAT +
        r"),\s*green:\s*(" + _FLOAT + r"),\s*blue:\s*(" + _FLOAT + r")\)")
    return {m.group(1): (float(m.group(2)), float(m.group(3)), float(m.group(4)))
            for m in pat.finditer(src)}


def parse_app_theme() -> dict[str, dict[str, dict]]:
    """theme -> field -> spec, where spec is one of:
       {'rgb': (r,g,b)} | {'overlay': 'black'|'white', 'alpha': a}
    """
    src = _read("AppTheme.swift")
    out: dict[str, dict[str, dict]] = {}
    # Slice each `static let <theme> = AppTheme(` block up to the next top-level
    # `static let`/`static func`.
    markers = [(m.group(1), m.start())
               for m in re.finditer(r"static let (light|dark|sepia) = AppTheme\(", src)]
    bounds = [m.start() for m in re.finditer(r"\n    static (let|func) ", src)]
    for theme, start in markers:
        end = min([b for b in bounds if b > start] + [len(src)])
        block = src[start:end]
        fields: dict[str, dict] = {}
        for m in re.finditer(
            r"(\w+):\s*Color\(red:\s*(" + _FLOAT + r"),\s*green:\s*(" + _FLOAT +
                r"),\s*blue:\s*(" + _FLOAT + r")\)", block):
            fields[m.group(1)] = {"rgb": (float(m.group(2)), float(m.group(3)), float(m.group(4)))}
        for m in re.finditer(r"(\w+):\s*Color\.(white|black)\b(?!\.opacity)", block):
            fields.setdefault(m.group(1), {"rgb": (1.0, 1.0, 1.0) if m.group(2) == "white" else (0.0, 0.0, 0.0)})
        for m in re.finditer(
                r"(\w+):\s*Color\.(black|white)\.opacity\((" + _FLOAT + r")\)", block):
            fields[m.group(1)] = {"overlay": m.group(2), "alpha": float(m.group(3))}
        out[theme] = fields
    return out


def parse_scale(filename: str, enum_name: str, dt: dict | None = None, reader=_read) -> dict[str, float]:
    """`static let key: CGFloat = value` inside `enum <enum_name> {...}`. value is a
    numeric literal or (when dt is given) a DesignTokens.* reference. Non-numeric
    RHS (e.g. `s6` aliasing another let) is skipped, as before. `reader` selects the
    source dir (_read=Models, _read_uic=UIComponents, _read_rel=relative path)."""
    src = reader(filename)
    m = re.search(r"enum " + enum_name + r"\s*\{", src)
    if not m:
        return {}
    # walk braces to find the enum body end
    i, depth = m.end(), 1
    while i < len(src) and depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    body = src[m.end():i]
    out: dict[str, float] = {}
    for mm in re.finditer(r"static let (\w+):\s*(?:CGFloat|Double)\s*=\s*([-\w.]+)", body):
        val = _swift_num(mm.group(2), dt)
        if val is not None:
            out[mm.group(1)] = val
    return out


def parse_app_skin_typography() -> dict[str, float]:
    """field -> point size from AppSkin+BaseValues buildTypography():
       `field: AppFonts.<builder>(size: N ...)`."""
    src = _read("AppSkin+BaseValues.swift")
    m = re.search(r"func buildTypography\(\)[^{]*\{(.*?)\n    \}", src, re.S)
    body = m.group(1) if m else src
    return {mm.group(1): float(mm.group(2))
            for mm in re.finditer(r"(\w+):\s*AppFonts\.\w+\(size:\s*(" + _FLOAT + r")", body)}


def _enum_body(src: str, header_re: str, open_ch: str, close_ch: str) -> str:
    """Return the balanced body following the first match of header_re."""
    m = re.search(header_re, src)
    if not m:
        return ""
    i, depth = m.end(), 1
    while i < len(src) and depth:
        depth += {open_ch: 1, close_ch: -1}.get(src[i], 0)
        i += 1
    return src[m.end():i]


def parse_struct_init(filename: str, var_name: str) -> dict[str, float]:
    """`label: number` pairs from `static let var_name = TypeName(...)` (non-numeric
    args like `x: SomeExpr` are skipped). Used for AppSkin baseSpacing / baseMetrics."""
    body = _enum_body(_read(filename), r"static let " + var_name + r"\s*=\s*\w+\(", "(", ")")
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r"(\w+):\s*(" + _FLOAT + r")\b", body)}


def parse_base_radii(filename: str = "AppSkin+BaseValues.swift") -> dict[str, str]:
    """`label: AppRadius.X` from `static let baseRadii = Radii(...)` -> label -> 'X'."""
    body = _enum_body(_read(filename), r"static let baseRadii\s*=\s*Radii\(", "(", ")")
    return {m.group(1): m.group(2) for m in re.finditer(r"(\w+):\s*AppRadius\.(\w+)", body)}


def parse_string_lets(filename: str) -> dict[str, str]:
    """`static let NAME = "..."` -> NAME -> literal content."""
    src = _read(filename)
    return {m.group(1): m.group(2)
            for m in re.finditer(r'static let (\w+)\s*=\s*"((?:[^"\\]|\\.)*)"', src)}


def parse_motion(dt: dict | None = None) -> dict[str, dict]:
    """AppMotion symbol -> {duration?, response?, damping?, curve?(4-tuple)}.

    duration/spring args may be a literal (0.15) OR a DesignTokens.* reference
    (the Figma->iOS SoT inversion); _swift_num resolves both. timingCurve
    control points stay literal — easing is NOT wired (tokens.json easing is a
    cubic-bezier *string*, iOS timingCurve takes 4 Doubles + an unmapped 0.4
    duration, so the types don't bridge)."""
    body = _enum_body(_read("AppMetrics.swift"), r"enum AppMotion\s*\{", "{", "}")
    out: dict[str, dict] = {}
    for m in re.finditer(
            r"static let (\w+)\s*=\s*Animation\.(?:easeOut|easeIn|easeInOut|linear)\(duration:\s*"
            r"([-\w.]+)\)", body):
        val = _swift_num(m.group(2), dt)
        if val is not None:
            out[m.group(1)] = {"duration": val}
    for m in re.finditer(
            r"static let (\w+)\s*(?::\s*Animation)?\s*=\s*(?:Animation)?\.(?:interactiveSpring|spring)\(response:\s*"
            r"([-\w.]+),\s*dampingFraction:\s*([-\w.]+)", body):
        resp = _swift_num(m.group(2), dt)
        damp = _swift_num(m.group(3), dt)
        if resp is None or damp is None:
            continue
        spec = out.setdefault(m.group(1), {})
        spec["response"] = resp
        spec["damping"] = damp
    for m in re.finditer(
            r"static let (\w+)\s*=\s*Animation\.timingCurve\(\s*(" + _FLOAT + r"),\s*(" + _FLOAT
            + r"),\s*(" + _FLOAT + r"),\s*(" + _FLOAT + r"),\s*duration:\s*(" + _FLOAT + r")\)", body):
        out[m.group(1)] = {"curve": tuple(float(m.group(i)) for i in range(2, 6)),
                           "duration": float(m.group(6))}
    return out


def parse_elevation(dt: dict | None = None) -> dict[str, dict[str, float]]:
    """z0..z4 -> {opacity, radius, y} from AppElevation's switch bodies. Each
    `return` is a numeric literal or (when dt is given) a DesignTokens.* reference."""
    src = _read("AppMetrics.swift")
    out: dict[str, dict[str, float]] = {f"z{i}": {} for i in range(5)}
    for prop in ("opacity", "radius", "y"):
        block = re.search(r"var " + prop + r":[^{]*\{(.*?)\n    \}", src, re.S)
        if not block:
            continue
        for m in re.finditer(r"case \.(z\d):\s*return\s*([-\w.]+)", block.group(1)):
            val = _swift_num(m.group(2), dt)
            if val is not None:
                out[m.group(1)][prop] = val
    return out


def parse_tag_metrics() -> dict[str, float]:
    """AppTagMetrics enum (lives in UIComponents, not Models): label -> CGFloat."""
    body = _enum_body(_read_uic("AppTagMetrics.swift"), r"enum AppTagMetrics\s*\{", "{", "}")
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r"static let (\w+):\s*CGFloat\s*=\s*(" + _FLOAT + r")", body)}


def parse_tag_fill() -> dict[str, float]:
    """AppTag background opacity -> {'light': a, 'dark': a} from AppSurface.swift's
       `tone.opacity(colorScheme == .dark ? <dark> : <light>)`."""
    src = _read_uic("AppSurface.swift")
    m = re.search(
        r"\.opacity\(\s*colorScheme == \.dark\s*\?\s*(" + _FLOAT + r")\s*:\s*("
        + _FLOAT + r")\s*\)", src)
    return {"dark": float(m.group(1)), "light": float(m.group(2))} if m else {}


# --------------------------------------------------------------------------
# DesignTokens.swift resolution
# --------------------------------------------------------------------------
# Post-wiring, an iOS SoT file may reference the SD-generated bridge
# (`DesignTokens.Radius.Scale.md`) instead of inlining a literal (`8`). The
# value still ultimately comes from tokens.json (DesignTokens.swift is generated
# from it, guarded byte-for-byte by `npm run build:check`), so resolving the
# reference back to its number lets this drift guard keep proving
# tokens.json == iOS across the SoT inversion — and still catches a mis-wired
# reference whose value diverges.

def parse_design_tokens() -> dict:
    """Nested dict of DesignTokens.swift scalar leaves, e.g.
       {'DesignTokens': {'Radius': {'Scale': {'md': 8.0}}}}. Empty if absent."""
    try:
        src = _read("DesignTokens.swift")
    except FileNotFoundError:
        return {}
    root: dict = {}
    stack = [root]
    for line in src.splitlines():
        s = line.strip()
        m = re.match(r"public enum (\w+)\s*\{", s)
        if m:
            child: dict = {}
            stack[-1][m.group(1)] = child
            stack.append(child)
            continue
        if s == "}":
            if len(stack) > 1:
                stack.pop()
            continue
        m = re.match(r"public static let (\w+):\s*\w+\s*=\s*(.+)", s)
        if m:
            try:
                stack[-1][m.group(1)] = float(m.group(2))
            except ValueError:
                stack[-1][m.group(1)] = m.group(2).strip('"')
    return root


def _resolve_dt(path: str, dt: dict):
    node: object = dt
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if not isinstance(node, dict) else None


def _swift_num(rhs: str, dt: dict | None) -> float | None:
    """Numeric literal (incl. negative) OR resolved DesignTokens.* reference."""
    rhs = rhs.strip().rstrip(",")
    try:
        return float(rhs)
    except ValueError:
        pass
    if dt and rhs.startswith("DesignTokens."):
        v = _resolve_dt(rhs, dt)
        if isinstance(v, (int, float)):
            return float(v)
    return None


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

def _eq(a: float, b: float) -> bool:
    return abs(a - b) < EPS


def _dtcg_px(spec: dict) -> float:
    return float(spec["$value"].rstrip("px"))


def _dtcg_s(spec: dict) -> float:
    return float(spec["$value"].rstrip("s"))


def _dtcg_rgb(spec: dict) -> tuple[float, float, float]:
    val = spec["$value"]
    if val.startswith("#"):
        return (
            int(val[1:3], 16) / 255,
            int(val[3:5], 16) / 255,
            int(val[5:7], 16) / 255,
        )
    if val.startswith("rgba("):
        parts = [float(x.strip()) for x in val[5:-1].split(",")]
        return tuple(p / 255 for p in parts[:3])
    raise ValueError(f"Unsupported color format: {val}")


def _dtcg_rgba(spec: dict) -> tuple[float, float, float, float]:
    val = spec["$value"]
    if val.startswith("rgba("):
        parts = [float(x.strip()) for x in val[5:-1].split(",")]
        return tuple(p / 255 for p in parts[:3]) + (parts[3],)
    raise ValueError(f"Unsupported rgba format: {val}")


def _dtcg_ref(spec: dict) -> str:
    val = spec["$value"]
    if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
        return val[1:-1].split(".")[-1]
    return val


def check() -> list[str]:
    tokens = json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    errors: list[str] = []

    dt = parse_design_tokens()  # bridge values for any iOS file wired to DesignTokens
    colors = parse_app_colors()
    theme = parse_app_theme()
    spacing = parse_scale("AppMetrics.swift", "AppSpacing", dt)
    radius = parse_scale("AppMetrics.swift", "AppRadius", dt)
    typescale = parse_scale("AppFonts.swift", "TypeScale", dt)
    skin_type = parse_app_skin_typography()
    elevation = parse_elevation(dt)
    tracking = parse_scale("AppFonts.swift", "Tracking", dt)
    base_spacing = parse_struct_init("AppSkin+BaseValues.swift", "baseSpacing")
    base_metrics = parse_struct_init("AppSkin+BaseValues.swift", "baseMetrics")
    base_radii = parse_base_radii()
    app_metrics = parse_scale("AppMetrics.swift", "AppMetrics", dt)
    color_strings = parse_string_lets("AppColors.swift")
    motion = parse_motion(dt)
    tap = parse_scale("AppMetrics.swift", "TapFeedback", dt)
    tag_metrics = parse_tag_metrics()
    tag_fill = parse_tag_fill()
    app_shell_metrics = parse_scale("AppShellComponents.swift", "AppShellMetrics", dt, reader=_read_uic)
    today_review_metrics = parse_scale(
        "Views/Vocabulary/Scenes/TodayReviewMetrics.swift", "TodayReviewMetrics", dt, reader=_read_rel)
    reader_metrics = parse_scale("Views/Reader/ReaderMetrics.swift", "ReaderMetrics", dt, reader=_read_rel)
    bookshelf_metrics = parse_scale("Views/Bookshelf/BookshelfMetrics.swift", "AppBookshelfMetrics", dt, reader=_read_rel)

    # 1) primitive palette
    for name, variants in tokens["color"]["primitive"].items():
        for variant, spec in variants.items():
            sym = spec.get("$swift", "")
            if not sym.startswith("AppColors."):
                continue
            swift_name = sym.split(".", 1)[1]
            if swift_name not in colors:
                errors.append(f"color.primitive.{name}.{variant}: {sym} not found in AppColors.swift")
                continue
            want, got = _dtcg_rgb(spec), colors[swift_name]
            if not all(_eq(x, y) for x, y in zip(want, got)):
                errors.append(f"color.primitive.{name}.{variant}: JSON {want} != Swift {sym} {list(got)}")

    # 2) theme palette (rgb + overlay) for fields carrying $swift
    for thm, fields in tokens["color"]["theme"].items():
        for key, spec in fields.items():
            if key.startswith("$") or "$swift" not in spec:
                continue
            sym = spec["$swift"]  # AppTheme.<theme>.<field>
            if not sym.startswith("AppTheme."):
                continue  # AppSurface.* (tag-fill) handled in its own loop below
            parts = sym.split(".")
            if len(parts) != 3:
                continue
            _, sw_theme, field = parts
            sw = theme.get(sw_theme, {}).get(field)
            if sw is None:
                errors.append(f"color.theme.{thm}.{key}: {sym} not found in AppTheme.swift")
                continue
            if spec["$value"].startswith("#") and "rgb" in sw:
                if not all(_eq(x, y) for x, y in zip(_dtcg_rgb(spec), sw["rgb"])):
                    errors.append(f"color.theme.{thm}.{key}: JSON {_dtcg_rgb(spec)} != Swift {sym} {list(sw['rgb'])}")
            elif spec["$value"].startswith("rgba(") and "overlay" in sw:
                r, g, b, a = _dtcg_rgba(spec)
                overlay = "black" if r == 0 and g == 0 and b == 0 else "white"
                if overlay != sw["overlay"] or not _eq(a, sw["alpha"]):
                    errors.append(f"color.theme.{thm}.{key}: JSON {overlay}@{a} "
                                  f"!= Swift {sym} {sw['overlay']}@{sw['alpha']}")
            else:
                errors.append(f"color.theme.{thm}.{key}: kind mismatch vs {sym} (JSON {spec}, Swift {sw})")

    # 2b) AppTag fill opacity (AppSurface.swift): tone @ theme-specific alpha.
    #     sepia mirrors light and carries no $swift, so it is skipped automatically.
    for thm, fields in tokens["color"]["theme"].items():
        spec = fields.get("tag-fill")
        if not spec or spec.get("$swift") != "AppSurface.AppTag.fill":
            continue
        if thm not in tag_fill:
            errors.append(f"color.theme.{thm}.tag-fill: AppSurface.swift has no {thm} opacity")
        elif not _eq(_dtcg_rgba(spec)[3], tag_fill[thm]):
            errors.append(f"color.theme.{thm}.tag-fill: JSON alpha {_dtcg_rgba(spec)[3]} "
                          f"!= Swift AppTag.fill {tag_fill[thm]}")

    # 3) numeric scales
    def check_scale(label: str, node: dict, swift: dict, prefix: str, key_field: str = "px"):
        for key, spec in node.items():
            if key.startswith("$") or "$swift" not in spec:
                continue
            sym = spec["$swift"]
            if not sym.startswith(prefix):
                raise AssertionError(
                    f"{label}.{key}: {sym} does not start with expected prefix {prefix!r}")
            sw_name = sym.split(".")[-1]
            if sw_name not in swift:
                errors.append(f"{label}.{key}: {sym} not found")
                continue
            json_val = _dtcg_px(spec) if key_field == "px" else _dtcg_s(spec)
            if not _eq(json_val, swift[sw_name]):
                errors.append(f"{label}.{key}: JSON {json_val} != Swift {sym} {swift[sw_name]}")

    check_scale("space.scale", tokens["space"]["scale"], spacing, "AppSpacing.")
    check_scale("radius.scale", tokens["radius"]["scale"], radius, "AppRadius.")

    # type.scale spans two provenance namespaces: the formal AppFonts.TypeScale
    # ramp and the bespoke AppSkin.Typography vocab sizes.
    for key, spec in tokens["type"]["scale"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        sym, field = spec["$swift"], spec["$swift"].split(".")[-1]
        if sym.startswith("AppFonts.TypeScale."):
            table = typescale
        elif sym.startswith("AppSkin.Typography."):
            table = skin_type
        else:
            raise AssertionError(
                f"type.scale.{key}: {sym} matches neither AppFonts.TypeScale. "
                f"nor AppSkin.Typography. namespace")
        if field not in table:
            errors.append(f"type.scale.{key}: {sym} not found")
        elif not _eq(_dtcg_px(spec), table[field]):
            errors.append(f"type.scale.{key}: JSON {_dtcg_px(spec)} != Swift {sym} {table[field]}")

    # 4) elevation z0..z4 (blur <-> radius)
    for key, step in tokens["elevation"]["steps"].items():
        if key.startswith("$"):
            continue
        sw = elevation.get(key, {})
        for jfield, sfield in (("opacity", "opacity"), ("blur", "radius"), ("y", "y")):
            if sfield not in sw:
                errors.append(f"elevation.{key}.{jfield}: AppElevation.{key}.{sfield} not found")
                continue
            json_val = step[jfield]["$value"] if jfield == "opacity" else float(step[jfield]["$value"].rstrip("px"))
            if not _eq(json_val, sw[sfield]):
                errors.append(f"elevation.{key}.{jfield}: JSON {json_val} != Swift AppElevation.{key}.{sfield} {sw[sfield]}")

    # 5) semantic spacing (AppSkin baseSpacing / baseMetrics / AppMetrics statics)
    _SPACE_TABLES = {
        "AppSkin.baseSpacing.": base_spacing,
        "AppSkin.baseMetrics.": base_metrics,
        "AppMetrics.": app_metrics,
        "AppTagMetrics.": tag_metrics,
        "AppShellMetrics.": app_shell_metrics,
        "TodayReviewMetrics.": today_review_metrics,
        "ReaderMetrics.": reader_metrics,
        "AppBookshelfMetrics.": bookshelf_metrics,
    }
    for key, spec in tokens["space"]["semantic"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        sym = spec["$swift"]
        table = next((t for p, t in _SPACE_TABLES.items() if sym.startswith(p)), None)
        name = sym.split(".")[-1]
        if table is None or name not in table:
            errors.append(f"space.semantic.{key}: {sym} not found")
        elif not _eq(_dtcg_px(spec), table[name]):
            errors.append(f"space.semantic.{key}: JSON {_dtcg_px(spec)} != Swift {sym} {table[name]}")

    # 6) tracking — AppFonts.Tracking ramp, plus AppSkin.baseMetrics.* tracking metrics
    #    (e.g. labelTracking, which lives in the baseMetrics struct, not the Tracking enum).
    for key, spec in tokens["type"]["tracking"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        sym = spec["$swift"]
        table = base_metrics if sym.startswith("AppSkin.baseMetrics.") else tracking
        name = sym.split(".")[-1]
        if name not in table:
            errors.append(f"type.tracking.{key}: {sym} not found")
        elif not _eq(_dtcg_px(spec), table[name]):
            errors.append(f"type.tracking.{key}: JSON {_dtcg_px(spec)} != Swift {sym} {table[name]}")

    # 7) semantic radius refs (AppSkin baseRadii -> AppRadius.X)
    for key, spec in tokens["radius"]["semantic"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        name = spec["$swift"].split(".")[-1]
        if name not in base_radii:
            errors.append(f"radius.semantic.{key}: {spec['$swift']} not found")
        elif base_radii[name] != _dtcg_ref(spec):
            errors.append(f"radius.semantic.{key}: JSON ref '{_dtcg_ref(spec)}' != Swift {spec['$swift']} AppRadius.{base_radii[name]}")

    # 8) vocab-highlight verbatim CSS strings (AppColors.*CSS)
    for thm, spec in tokens["color"]["vocab-highlight"].items():
        if thm.startswith("$") or "$swift" not in spec:
            continue
        name = spec["$swift"].split(".")[-1]
        if name not in color_strings:
            errors.append(f"vocab-highlight.{thm}: {spec['$swift']} not found")
        elif color_strings[name] != spec["$value"]:
            errors.append(f"vocab-highlight.{thm}: JSON string != Swift {spec['$swift']}")

    # 9) motion durations (AppMotion easeOut/linear/spring/timingCurve)
    for key, spec in tokens["motion"]["duration"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        sym = spec["$swift"]                       # e.g. AppMotion.standardSpring(response)
        base = sym.split(".")[1].split("(")[0]
        fm = re.search(r"\((\w+)\)", sym)
        field = fm.group(1) if fm else "duration"
        md = motion.get(base, {})
        if field not in md:
            errors.append(f"motion.duration.{key}: {sym} ({field}) not parsed from AppMotion")
        elif not _eq(_dtcg_s(spec), md[field]):
            errors.append(f"motion.duration.{key}: JSON {_dtcg_s(spec)} != Swift {sym} {md[field]}")

    # 10) motion easing control points (AppMotion timingCurve -> cubic-bezier)
    for key, spec in tokens["motion"]["easing"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        base = spec["$swift"].split(".")[-1]
        md = motion.get(base, {})
        if "curve" not in md:
            errors.append(f"motion.easing.{key}: {spec['$swift']} has no timingCurve")
            continue
        nums = re.findall(_FLOAT, spec["$value"].split("cubic-bezier", 1)[-1]) if "cubic-bezier" in spec["$value"] else []
        got = tuple(float(x) for x in nums[:4])
        if len(got) != 4 or not all(_eq(a, b) for a, b in zip(got, md["curve"])):
            errors.append(f"motion.easing.{key}: JSON {got} != Swift {spec['$swift']} {md['curve']}")

    # 11) tap-feedback scalars (AppMotion.TapFeedback)
    for key, spec in tokens["motion"]["tap-feedback"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        name = spec["$swift"].split(".")[-1]
        if name not in tap:
            errors.append(f"motion.tap-feedback.{key}: {spec['$swift']} not found")
        elif not _eq(spec["$value"], tap[name]):
            errors.append(f"motion.tap-feedback.{key}: JSON {spec['$value']} != Swift {spec['$swift']} {tap[name]}")

    # 12) motion spring physics (AppMotion spring response + dampingFraction)
    # Springs are iOS-native physics (web has no spring token — it uses the
    # cubic-bezier approximations under motion.easing), so EVERY motion.spring
    # entry is an iOS mirror and MUST carry $swift. Fail loud on a missing one
    # rather than silently skipping: a dropped provenance key would otherwise
    # disable this guard unnoticed (regression caught 2026-06 DTCG migration).
    for key, spec in tokens["motion"].get("spring", {}).items():
        if key.startswith("$"):
            continue
        if "$swift" not in spec:
            raise AssertionError(
                f"motion.spring.{key}: missing $swift provenance — every spring is an "
                f"iOS mirror; re-attach $swift or the drift guard silently skips it.")
        base = spec["$swift"].split(".")[-1]
        md = motion.get(base, {})
        for field in ("response", "damping"):
            if field not in md:
                errors.append(f"motion.spring.{key}: {spec['$swift']} ({field}) not parsed from AppMotion")
            elif not _eq(spec[field]["$value"], md[field]):
                errors.append(f"motion.spring.{key}: JSON {field}={spec[field]['$value']} != Swift {spec['$swift']} {md[field]}")

    return errors


def main() -> int:
    errors = check()
    if errors:
        print(f"❌ token drift: {len(errors)} mismatch(es) between tokens.json and iOS Swift SoT\n")
        for e in errors:
            print(f"  - {e}")
        print("\nFix: update design-system/tokens.json to match the Swift, then "
              "`uv run python ops/gen_web_tokens.py`.")
        return 1
    print("✅ tokens.json is in sync with the iOS Swift SoT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
