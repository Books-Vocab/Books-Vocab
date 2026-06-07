#!/usr/bin/env -S uv run --python 3.13 python
"""One-time migration: KG tokens.json → W3C DTCG tokens.json.

Run: uv run python ops/migrate_tokens_to_dtcg.py
Then: mv design-system/tokens-dtcg.json design-system/tokens.json
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "design-system" / "tokens.json"
DST = REPO / "design-system" / "tokens-dtcg.json"


def _rgb_to_hex(rgb: list[float]) -> str:
    r, g, b = rgb
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _overlay_to_rgba(overlay: str, alpha: float) -> str:
    if overlay == "black":
        return f"rgba(0,0,0,{alpha})"
    if overlay == "white":
        return f"rgba(255,255,255,{alpha})"
    raise ValueError(f"Unknown overlay: {overlay}")


def _overlay_rgb_to_rgba(rgb: list[float], alpha: float) -> str:
    r, g, b = rgb
    return f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)},{alpha})"


def _resolve_color_rgb(ref_path: str, full_data: dict) -> list[float] | None:
    """Resolve a color reference like 'accent.light' to its [r,g,b]."""
    parts = ref_path.split(".")
    node = full_data.get("color", {}).get("primitive", {})
    for part in parts:
        if part not in node:
            return None
        node = node[part]
    return node.get("rgb")


def _make_description(node: dict) -> str:
    parts = []
    if "$swift" in node:
        parts.append(node["$swift"])
    if "$note" in node:
        parts.append(node["$note"])
    return " — ".join(parts)


def _is_leaf_token(node) -> bool:
    if not isinstance(node, dict):
        return False
    token_keys = {
        "rgb", "overlay", "overlay-rgb", "ref", "css", "px", "ratio", "s",
        "opacity", "blur", "y", "response", "damping", "value",
    }
    has_value_key = any(k in node for k in token_keys)
    if not has_value_key:
        return False
    # A true leaf has no nested dicts under non-metadata keys
    for k, v in node.items():
        if k.startswith("$"):
            continue
        if isinstance(v, dict):
            return False
    return True


def _convert_leaf(node: dict, path: str, full_data: dict) -> dict:
    """Convert a leaf token node to DTCG format."""
    desc = _make_description(node)
    swift = node.get("$swift")

    def _with_swift(result: dict) -> dict:
        if swift:
            result["$swift"] = swift
        return result

    # ── Color: literal rgb ──────────────────────────────────────
    if "rgb" in node:
        return _with_swift({
            "$type": "color",
            "$value": _rgb_to_hex(node["rgb"]),
            **({"$description": desc} if desc else {}),
        })

    # ── Color: overlay (black/white) + alpha ────────────────────
    if "overlay" in node and "alpha" in node and "overlay-rgb" not in node:
        return _with_swift({
            "$type": "color",
            "$value": _overlay_to_rgba(node["overlay"], node["alpha"]),
            **({"$description": desc} if desc else {}),
        })

    # ── Color: overlay-rgb + alpha ──────────────────────────────
    if "overlay-rgb" in node and "alpha" in node:
        return _with_swift({
            "$type": "color",
            "$value": _overlay_rgb_to_rgba(node["overlay-rgb"], node["alpha"]),
            **({"$description": desc} if desc else {}),
        })

    # ── Color: reference (with optional alpha) ──────────────────
    if "ref" in node:
        ref_path = node["ref"]

        # Build full DTCG reference path
        if path.startswith("color.theme.") or path.startswith("web-only.theme-color."):
            full_ref = f"color.primitive.{ref_path}"
        elif path.startswith("radius.semantic."):
            full_ref = f"radius.scale.{ref_path}"
        else:
            full_ref = ref_path

        if "alpha" in node:
            rgb = _resolve_color_rgb(ref_path, full_data)
            if rgb:
                r = round(rgb[0] * 255)
                g = round(rgb[1] * 255)
                b = round(rgb[2] * 255)
                val = f"rgba({r},{g},{b},{node['alpha']})"
            else:
                val = f"{{{full_ref}}}"
        else:
            val = f"{{{full_ref}}}"

        # Determine $type from context
        if path.startswith("radius.semantic."):
            token_type = "dimension"
        elif path.startswith("color.") or path.startswith("web-only.theme-color."):
            token_type = "color"
        else:
            token_type = "color"  # default

        return _with_swift({
            "$type": token_type,
            "$value": val,
            **({"$description": desc} if desc else {}),
        })

    # ── CSS string (vocab-highlight, web-only invariant) ────────
    if "css" in node:
        val = node["css"]
        if val.endswith("px"):
            token_type = "dimension"
        elif val.startswith("#") and len(val) in (4, 7, 9):
            token_type = "color"
        else:
            token_type = "string"
        return _with_swift({
            "$type": token_type,
            "$value": val,
            **({"$description": desc} if desc else {}),
        })

    # ── Dimension: px ───────────────────────────────────────────
    if "px" in node:
        return _with_swift({
            "$type": "dimension",
            "$value": f"{node['px']}px",
            **({"$description": desc} if desc else {}),
        })

    # ── Number: ratio ───────────────────────────────────────────
    if "ratio" in node:
        return _with_swift({
            "$type": "number",
            "$value": node["ratio"],
            **({"$description": desc} if desc else {}),
        })

    # ── Time: seconds ───────────────────────────────────────────
    if "s" in node:
        return _with_swift({
            "$type": "time",
            "$value": f"{node['s']}s",
            **({"$description": desc} if desc else {}),
        })

    # ── Number: generic value (tap-feedback) ────────────────────
    if "value" in node:
        return _with_swift({
            "$type": "number",
            "$value": node["value"],
            **({"$description": desc} if desc else {}),
        })

    # ── Elevation step composite (object-level $swift preserved) ──
    # Multi-scalar objects decompose into sub-leaves; the parent $swift must
    # ride along at the object level so the drift guard's provenance anchor
    # survives (token_drift_check elevation/spring sections key off it).
    if "opacity" in node and "blur" in node and "y" in node:
        return _with_swift({
            "opacity": {
                "$type": "number",
                "$value": node["opacity"],
            },
            "blur": {
                "$type": "dimension",
                "$value": f"{node['blur']}px",
            },
            "y": {
                "$type": "dimension",
                "$value": f"{node['y']}px",
            },
        })

    # ── Spring composite (object-level $swift preserved) ─────────
    if "response" in node and "damping" in node:
        return _with_swift({
            "response": {
                "$type": "number",
                "$value": node["response"],
            },
            "damping": {
                "$type": "number",
                "$value": node["damping"],
            },
        })

    raise ValueError(f"Unrecognised leaf node at {path}: {node}")


def _walk(obj, path: str, full_data: dict):
    if isinstance(obj, dict):
        if _is_leaf_token(obj):
            return _convert_leaf(obj, path, full_data)

        result: dict = {}
        for key, value in obj.items():
            # Preserve metadata / comment keys verbatim
            if key.startswith("$"):
                if key in (
                    "$name", "$description", "$provenance", "$platform-equivalence",
                    "$comment", "$comment2", "$comment3",
                    "$comment-mono", "$comment-display", "$comment-spring",
                ):
                    result[key] = value
                continue

            new_path = f"{path}.{key}" if path else key

            # String values → wrap as token (fontFamily, transition, etc.)
            if isinstance(value, str):
                if "family" in new_path:
                    result[key] = {"$type": "fontFamily", "$value": value}
                else:
                    result[key] = {"$type": "string", "$value": value}
                continue

            # Numeric values → wrap as number token (e.g. elevation.dark-boost)
            if isinstance(value, (int, float)):
                result[key] = {"$type": "number", "$value": value}
                continue

            result[key] = _walk(value, new_path, full_data)
        return result

    if isinstance(obj, list):
        return [_walk(item, f"{path}[{i}]", full_data) for i, item in enumerate(obj)]

    return obj


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    converted = _walk(data, "", data)

    # Also preserve top-level $platform-equivalence if it got dropped
    if "$platform-equivalence" in data and "$platform-equivalence" not in converted:
        converted["$platform-equivalence"] = data["$platform-equivalence"]

    DST.write_text(json.dumps(converted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {DST}  ({len(json.dumps(converted))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
