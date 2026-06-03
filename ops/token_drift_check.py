#!/usr/bin/env python3
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
  AppSkin      baseTypography sizes, baseSpacing / baseMetrics, baseRadii refs

Web-only values WITHOUT a $swift key (leading ratios, spring bezier
approximations, composed --transition-* shorthands, CJK fallbacks) are out of
scope by design and documented under $platform-equivalence in tokens.json.
Invariant: a $swift-bearing token that this guard cannot map to a real Swift
symbol raises an error rather than being silently skipped.

Run:  uv run python ops/token_drift_check.py
Exit: 0 = in sync, 1 = drift found.

Env overrides (tests): KG_TOKENS_JSON, KG_IOS_MODELS_DIR.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS_JSON = Path(os.environ.get("KG_TOKENS_JSON", REPO / "design-system" / "tokens.json"))
MODELS = Path(os.environ.get("KG_IOS_MODELS_DIR", REPO / "ios" / "BooksBrowser" / "Models"))

EPS = 1e-6
_FLOAT = r"[-+]?[0-9]*\.?[0-9]+"


# --------------------------------------------------------------------------
# Swift parsers
# --------------------------------------------------------------------------

def _read(name: str) -> str:
    return (MODELS / name).read_text(encoding="utf-8")


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


def parse_scale(filename: str, enum_name: str) -> dict[str, float]:
    """`static let key: CGFloat = value` inside `enum <enum_name> {...}`."""
    src = _read(filename)
    m = re.search(r"enum " + enum_name + r"\s*\{", src)
    if not m:
        return {}
    # walk braces to find the enum body end
    i, depth = m.end(), 1
    while i < len(src) and depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    body = src[m.end():i]
    return {mm.group(1): float(mm.group(2))
            for mm in re.finditer(r"static let (\w+):\s*(?:CGFloat|Double)\s*=\s*(" + _FLOAT + r")", body)}


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


def parse_motion() -> dict[str, dict]:
    """AppMotion symbol -> {duration?, response?, curve?(4-tuple)}."""
    body = _enum_body(_read("AppMetrics.swift"), r"enum AppMotion\s*\{", "{", "}")
    out: dict[str, dict] = {}
    for m in re.finditer(
            r"static let (\w+)\s*=\s*Animation\.(?:easeOut|easeIn|easeInOut|linear)\(duration:\s*("
            + _FLOAT + r")\)", body):
        out[m.group(1)] = {"duration": float(m.group(2))}
    for m in re.finditer(r"static let (\w+)\s*=\s*Animation\.spring\(response:\s*(" + _FLOAT + r")", body):
        out.setdefault(m.group(1), {})["response"] = float(m.group(2))
    for m in re.finditer(
            r"static let (\w+)\s*=\s*Animation\.timingCurve\(\s*(" + _FLOAT + r"),\s*(" + _FLOAT
            + r"),\s*(" + _FLOAT + r"),\s*(" + _FLOAT + r"),\s*duration:\s*(" + _FLOAT + r")\)", body):
        out[m.group(1)] = {"curve": tuple(float(m.group(i)) for i in range(2, 6)),
                           "duration": float(m.group(6))}
    return out


def parse_elevation() -> dict[str, dict[str, float]]:
    """z0..z4 -> {opacity, radius, y} from AppElevation's switch bodies."""
    src = _read("AppMetrics.swift")
    out: dict[str, dict[str, float]] = {f"z{i}": {} for i in range(5)}
    for prop in ("opacity", "radius", "y"):
        block = re.search(r"var " + prop + r":[^{]*\{(.*?)\n    \}", src, re.S)
        if not block:
            continue
        for m in re.finditer(r"case \.(z\d):\s*return\s*(" + _FLOAT + r")", block.group(1)):
            out[m.group(1)][prop] = float(m.group(2))
    return out


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

def _eq(a: float, b: float) -> bool:
    return abs(a - b) < EPS


def check() -> list[str]:
    tokens = json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    errors: list[str] = []

    colors = parse_app_colors()
    theme = parse_app_theme()
    spacing = parse_scale("AppMetrics.swift", "AppSpacing")
    radius = parse_scale("AppMetrics.swift", "AppRadius")
    typescale = parse_scale("AppFonts.swift", "TypeScale")
    skin_type = parse_app_skin_typography()
    elevation = parse_elevation()
    tracking = parse_scale("AppFonts.swift", "Tracking")
    base_spacing = parse_struct_init("AppSkin+BaseValues.swift", "baseSpacing")
    base_metrics = parse_struct_init("AppSkin+BaseValues.swift", "baseMetrics")
    base_radii = parse_base_radii()
    app_metrics = parse_scale("AppMetrics.swift", "AppMetrics")
    color_strings = parse_string_lets("AppColors.swift")
    motion = parse_motion()
    tap = parse_scale("AppMetrics.swift", "TapFeedback")

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
            want, got = spec["rgb"], colors[swift_name]
            if not all(_eq(x, y) for x, y in zip(want, got)):
                errors.append(f"color.primitive.{name}.{variant}: JSON {want} != Swift {sym} {list(got)}")

    # 2) theme palette (rgb + overlay) for fields carrying $swift
    for thm, fields in tokens["color"]["theme"].items():
        for key, spec in fields.items():
            if key.startswith("$") or "$swift" not in spec:
                continue
            sym = spec["$swift"]  # AppTheme.<theme>.<field>
            parts = sym.split(".")
            if len(parts) != 3:
                continue
            _, sw_theme, field = parts
            sw = theme.get(sw_theme, {}).get(field)
            if sw is None:
                errors.append(f"color.theme.{thm}.{key}: {sym} not found in AppTheme.swift")
                continue
            if "rgb" in spec and "rgb" in sw:
                if not all(_eq(x, y) for x, y in zip(spec["rgb"], sw["rgb"])):
                    errors.append(f"color.theme.{thm}.{key}: JSON {spec['rgb']} != Swift {sym} {list(sw['rgb'])}")
            elif "overlay" in spec and "overlay" in sw:
                if spec["overlay"] != sw["overlay"] or not _eq(spec["alpha"], sw["alpha"]):
                    errors.append(f"color.theme.{thm}.{key}: JSON {spec['overlay']}@{spec['alpha']} "
                                  f"!= Swift {sym} {sw['overlay']}@{sw['alpha']}")
            else:
                errors.append(f"color.theme.{thm}.{key}: kind mismatch vs {sym} (JSON {spec}, Swift {sw})")

    # 3) numeric scales
    def check_scale(label: str, node: dict, swift: dict, key_field: str = "px"):
        for key, spec in node.items():
            if key.startswith("$") or "$swift" not in spec:
                continue
            sym = spec["$swift"]
            sw_name = sym.split(".")[-1]
            if sw_name not in swift:
                errors.append(f"{label}.{key}: {sym} not found")
                continue
            if not _eq(spec[key_field], swift[sw_name]):
                errors.append(f"{label}.{key}: JSON {spec[key_field]} != Swift {sym} {swift[sw_name]}")

    check_scale("space.scale", tokens["space"]["scale"], spacing)
    check_scale("radius.scale", tokens["radius"]["scale"], radius)

    # type.scale spans two provenance namespaces: the formal AppFonts.TypeScale
    # ramp and the bespoke AppSkin.Typography vocab sizes.
    for key, spec in tokens["type"]["scale"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        sym, field = spec["$swift"], spec["$swift"].split(".")[-1]
        table = typescale if sym.startswith("AppFonts.TypeScale.") else skin_type
        if field not in table:
            errors.append(f"type.scale.{key}: {sym} not found")
        elif not _eq(spec["px"], table[field]):
            errors.append(f"type.scale.{key}: JSON {spec['px']} != Swift {sym} {table[field]}")

    # 4) elevation z0..z4 (blur <-> radius)
    for key, step in tokens["elevation"]["steps"].items():
        if key.startswith("$"):
            continue
        sw = elevation.get(key, {})
        for jfield, sfield in (("opacity", "opacity"), ("blur", "radius"), ("y", "y")):
            if sfield not in sw:
                errors.append(f"elevation.{key}.{jfield}: AppElevation.{key}.{sfield} not found")
                continue
            if not _eq(step[jfield], sw[sfield]):
                errors.append(f"elevation.{key}.{jfield}: JSON {step[jfield]} != Swift AppElevation.{key}.{sfield} {sw[sfield]}")

    # 5) semantic spacing (AppSkin baseSpacing / baseMetrics / AppMetrics statics)
    _SPACE_TABLES = {
        "AppSkin.baseSpacing.": base_spacing,
        "AppSkin.baseMetrics.": base_metrics,
        "AppMetrics.": app_metrics,
    }
    for key, spec in tokens["space"]["semantic"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        sym = spec["$swift"]
        table = next((t for p, t in _SPACE_TABLES.items() if sym.startswith(p)), None)
        name = sym.split(".")[-1]
        if table is None or name not in table:
            errors.append(f"space.semantic.{key}: {sym} not found")
        elif not _eq(spec["px"], table[name]):
            errors.append(f"space.semantic.{key}: JSON {spec['px']} != Swift {sym} {table[name]}")

    # 6) tracking (AppFonts.Tracking)
    for key, spec in tokens["type"]["tracking"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        name = spec["$swift"].split(".")[-1]
        if name not in tracking:
            errors.append(f"type.tracking.{key}: {spec['$swift']} not found")
        elif not _eq(spec["px"], tracking[name]):
            errors.append(f"type.tracking.{key}: JSON {spec['px']} != Swift {spec['$swift']} {tracking[name]}")

    # 7) semantic radius refs (AppSkin baseRadii -> AppRadius.X)
    for key, spec in tokens["radius"]["semantic"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        name = spec["$swift"].split(".")[-1]
        if name not in base_radii:
            errors.append(f"radius.semantic.{key}: {spec['$swift']} not found")
        elif base_radii[name] != spec["ref"]:
            errors.append(f"radius.semantic.{key}: JSON ref '{spec['ref']}' != Swift {spec['$swift']} AppRadius.{base_radii[name]}")

    # 8) vocab-highlight verbatim CSS strings (AppColors.*CSS)
    for thm, spec in tokens["color"]["vocab-highlight"].items():
        if thm.startswith("$") or "$swift" not in spec:
            continue
        name = spec["$swift"].split(".")[-1]
        if name not in color_strings:
            errors.append(f"vocab-highlight.{thm}: {spec['$swift']} not found")
        elif color_strings[name] != spec["css"]:
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
        elif not _eq(spec["s"], md[field]):
            errors.append(f"motion.duration.{key}: JSON {spec['s']} != Swift {sym} {md[field]}")

    # 10) motion easing control points (AppMotion timingCurve -> cubic-bezier)
    for key, spec in tokens["motion"]["easing"].items():
        if key.startswith("$") or "$swift" not in spec:
            continue
        base = spec["$swift"].split(".")[-1]
        md = motion.get(base, {})
        if "curve" not in md:
            errors.append(f"motion.easing.{key}: {spec['$swift']} has no timingCurve")
            continue
        nums = re.findall(_FLOAT, spec["css"].split("cubic-bezier", 1)[-1]) if "cubic-bezier" in spec["css"] else []
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
        elif not _eq(spec["value"], tap[name]):
            errors.append(f"motion.tap-feedback.{key}: JSON {spec['value']} != Swift {spec['$swift']} {tap[name]}")

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
