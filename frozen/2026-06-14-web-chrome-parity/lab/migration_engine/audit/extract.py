#!/usr/bin/env -S uv run python
"""One-shot delta-audit extractor for the iOS->Web migration engine.

Scans the hand-aligned web surface CSS + shared component/harness CSS, pulls every
hard-coded numeric value (px / unitless / deg) with selector context, declaration,
surface, and the nearest comment block (which usually carries iOS-provenance /
`measured` annotation).

Then:
  - classifies each value against the kg-tokens.css scalar table (token-explicable?)
  - clusters identical value+normalized-property-class across surfaces
    (>=2 -> L2 candidate, ==1 -> orphan / suspected overfit)

Outputs measured_values.json. report.md is written by report.py off this JSON.
Pure stdlib; no deps. Run: uv run python lab/migration_engine/audit/extract.py
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web" / "src"
SURF_DIR = WEB / "surfaces"
STYLES = WEB / "styles"

# Per-surface CSS + shared component + harness CSS. kg-tokens.css is the GENERATED
# token table (the L1 source of truth), parsed separately as the token map.
TARGETS: list[Path] = sorted(SURF_DIR.glob("*/*.css")) + [
    STYLES / "kg-components.css",
    STYLES / "harness.css",
]
TOKENS_CSS = STYLES / "kg-tokens.css"

COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
DECL_RE = re.compile(r"(?P<prop>[\w-]+)\s*:\s*(?P<val>[^;{}]+);", re.MULTILINE)
NUM_TOKEN_RE = re.compile(r"(?<![\w.#-])(-?\d+(?:\.\d+)?)(px|deg|em|rem|%)?(?![\w.])")

SKIP_PROPS = {
    "z-index", "flex", "order", "flex-grow", "flex-shrink", "-webkit-line-clamp",
    "grid-row", "grid-column", "tab-size", "columns", "opacity",
}


def build_token_px_map() -> dict[str, set[str]]:
    text = TOKENS_CSS.read_text()
    raw: dict[str, str] = {}
    for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", text):
        raw[m.group(1)] = m.group(2).strip()

    def resolve(val: str, depth: int = 0) -> str:
        if depth > 5:
            return val
        m = re.fullmatch(r"var\((--[\w-]+)\)", val.strip())
        if m and m.group(1) in raw:
            return resolve(raw[m.group(1)], depth + 1)
        return val

    px_map: dict[str, set[str]] = defaultdict(set)
    for name, val in raw.items():
        rv = resolve(val)
        for num in re.findall(r"(?<![\w.#])(\d+(?:\.\d+)?)px", rv):
            px_map[name].add(num)
        if re.fullmatch(r"\d+(?:\.\d+)?", rv):
            px_map[name].add(rv)
    return px_map


def build_value_to_tokens(px_map: dict[str, set[str]]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = defaultdict(list)
    for name, vals in px_map.items():
        for v in vals:
            rev[v].append(name)
    return {k: sorted(v) for k, v in rev.items()}


def _clean_comment(c: str) -> str:
    inner = c[2:-2]
    lines = [ln.strip().lstrip("*").strip() for ln in inner.splitlines()]
    return " ".join(ln for ln in lines if ln).strip()


def nearest_comment(pos: int, comments: list[tuple[int, int, str]]) -> str:
    best = ""
    best_end = -1
    for start, end, body in comments:
        if end <= pos:
            best, best_end = body, end
        else:
            break
    if best and pos - best_end < 900:
        return _clean_comment(best)
    return ""


def selector_for(text: str, pos: int) -> str:
    brace = text.rfind("{", 0, pos)
    if brace == -1:
        return "(root)"
    seg_start = max(
        text.rfind("}", 0, brace),
        text.rfind("*/", 0, brace),
        text.rfind(";", 0, brace),
    )
    sel = text[(seg_start + 1) if seg_start >= 0 else 0:brace]
    sel = COMMENT_RE.sub("", sel)
    return re.sub(r"\s+", " ", sel).strip() or "(root)"


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def prop_class(prop: str) -> str:
    if "padding" in prop:
        return "padding"
    if "margin" in prop:
        return "margin"
    if prop in ("gap", "row-gap", "column-gap", "grid-gap"):
        return "gap"
    if prop in ("width", "min-width", "max-width"):
        return "width"
    if prop in ("height", "min-height", "max-height"):
        return "height"
    if "radius" in prop:
        return "radius"
    if "font-size" in prop:
        return "font-size"
    if "line-height" in prop:
        return "line-height"
    if prop in ("top", "right", "bottom", "left", "inset"):
        return "offset"
    if "border" in prop:
        return "border"
    if "letter-spacing" in prop:
        return "tracking"
    return prop


def main() -> None:
    value_to_tokens = build_value_to_tokens(build_token_px_map())
    records: list[dict] = []

    for path in TARGETS:
        if not path.exists():
            continue
        rel = str(path.relative_to(ROOT))
        surface = path.parent.name if path.parent.name != "styles" else f"shared:{path.stem}"
        text = path.read_text()
        comments = [(m.start(), m.end(), m.group(0)) for m in COMMENT_RE.finditer(text)]
        scrub = COMMENT_RE.sub(lambda m: " " * (m.end() - m.start()), text)

        for dm in DECL_RE.finditer(scrub):
            prop = dm.group("prop").strip().lower()
            val = dm.group("val").strip()
            if prop in SKIP_PROPS or prop.startswith("--"):
                continue
            comment = nearest_comment(dm.start(), comments)
            sel = selector_for(text, dm.start())
            ln = line_of(text, dm.start())
            seen_in_decl: set[str] = set()
            for nm in NUM_TOKEN_RE.finditer(val):
                num, unit = nm.group(1), (nm.group(2) or "")
                if unit in ("em", "rem", "%"):
                    continue
                # de-dupe identical literal within one declaration (e.g. shorthand)
                if num in seen_in_decl:
                    continue
                seen_in_decl.add(num)
                records.append({
                    "value": float(num),
                    "literal": num,
                    "unit": unit or "n",
                    "prop": prop,
                    "full_value": val,
                    "selector": sel,
                    "surface": surface,
                    "file": rel,
                    "line": ln,
                    "comment": comment,
                    "token_explicable": num in value_to_tokens,
                    "matching_tokens": value_to_tokens.get(num, []),
                    "measured_flag": "measured" in comment.lower(),
                })

    clusters: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        clusters[(prop_class(r["prop"]), r["literal"])].append(r)

    cluster_out = []
    for (pclass, literal), members in clusters.items():
        surfaces = sorted({m["surface"] for m in members})
        cluster_out.append({
            "prop_class": pclass,
            "literal": literal,
            "n_occurrences": len(members),
            "n_surfaces": len(surfaces),
            "surfaces": surfaces,
            "token_explicable": members[0]["token_explicable"],
            "matching_tokens": members[0]["matching_tokens"],
            "any_measured": any(m["measured_flag"] for m in members),
            "kind": (
                "token" if members[0]["token_explicable"]
                else "L2_candidate" if len(surfaces) >= 2
                else "orphan"
            ),
            "provenance": [
                {"file": m["file"], "line": m["line"], "selector": m["selector"],
                 "prop": m["prop"], "comment": m["comment"]}
                for m in members
            ],
        })
    cluster_out.sort(key=lambda c: (-c["n_surfaces"], -c["n_occurrences"]))

    out = {
        "meta": {
            "root": str(ROOT),
            "targets": [str(p.relative_to(ROOT)) for p in TARGETS if p.exists()],
            "token_table": str(TOKENS_CSS.relative_to(ROOT)),
            "n_records": len(records),
            "n_clusters": len(cluster_out),
        },
        "token_px_index": value_to_tokens,
        "records": records,
        "clusters": cluster_out,
    }
    out_path = Path(__file__).parent / "measured_values.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {out_path} : {len(records)} records, {len(cluster_out)} clusters")


if __name__ == "__main__":
    main()
