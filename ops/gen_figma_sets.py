#!/usr/bin/env python3
"""Project tokens.json → Tokens Studio multi-set sidecar (read-only view).

The single source of truth is ``design-system/tokens.json`` (consumed by the
generation chain — gen_web_tokens.py / token_drift_check.py / sd.config.mjs — all
of which read that ONE fixed path). This script projects it, ONE-WAY, into
``design-system/.tokens-studio/tokens/`` as Tokens Studio token *sets* so a
designer can import that folder in the Tokens Studio Figma plugin and get
light/dark/sepia theme switching — WITHOUT touching the generation chain and
WITHOUT a Tokens Studio Pro licence (the ``$themes.json`` is pre-authored here,
not built in the paid plugin UI).

The sidecar is a READ-ONLY view: never edit it by hand, never sync back from it.
Colour edits round-trip through ``tokens.json`` (+ the iOS literal SoT + WCAG
gate) — see docs/sop/figma-token-workflow.md. ``--check`` fails if the sidecar
has drifted from tokens.json (wire it into CI like the other generators).

Set layout:
  core.json         color.primitive + space + radius + type + elevation + motion  (mode-invariant)
  theme-light.json  color.theme.light  + vocab-highlight.light   → path collapsed to color.theme.* / color.vocab-highlight
  theme-dark.json   color.theme.dark   + vocab-highlight.dark
  theme-sepia.json  color.theme.sepia  + vocab-highlight.sepia
  $metadata.json    tokenSetOrder
  $themes.json      Light/Dark/Sepia, each enabling core(source)+its theme set
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "design-system" / "tokens.json"
OUT = ROOT / "design-system" / ".tokens-studio" / "tokens"
# single merged file: first-level keys = set names + $themes/$metadata. This is
# the import entry for browser-based Figma (Tokens Studio's "Choose folder" needs
# the desktop app; "Choose file" takes this one file). See README.md.
BUNDLE = ROOT / "design-system" / ".tokens-studio" / "bundle.json"

# mode-invariant scalar branches shared by every theme (live in the core set)
CORE_BRANCHES = ["space", "radius", "type", "elevation", "motion"]
THEMES = ["light", "dark", "sepia"]


def build_sets(d: dict) -> dict[str, dict]:
    sets: dict[str, dict] = {}
    # core: primitive colours + all mode-invariant scalar branches
    core: dict = {"color": {"primitive": d["color"]["primitive"]}}
    for b in CORE_BRANCHES:
        if b in d:
            core[b] = d[b]
    sets["core"] = core
    # per-theme: semantic colours collapsed to color.theme.* (so the three sets
    # share token paths → Tokens Studio can switch between them) + vocab-highlight
    for t in THEMES:
        s: dict = {"color": {"theme": d["color"]["theme"][t]}}
        vh = d["color"].get("vocab-highlight", {}).get(t)
        if vh is not None:
            s["color"]["vocab-highlight"] = vh
        sets[f"theme-{t}"] = s
    return sets


def build_metadata() -> dict:
    return {"tokenSetOrder": ["core", "theme-light", "theme-dark", "theme-sepia"]}


def build_themes() -> list[dict]:
    out = []
    for t in THEMES:
        sel = {"core": "source"}
        for u in THEMES:
            sel[f"theme-{u}"] = "enabled" if u == t else "disabled"
        out.append({
            "id": f"kg-{t}",
            "name": t.capitalize(),
            "group": "theme",
            "selectedTokenSets": sel,
        })
    return out


def render() -> dict[str, object]:
    d = json.loads(TOKENS.read_text())
    files: dict[str, object] = {}
    for name, content in build_sets(d).items():
        files[f"{name}.json"] = content
    files["$metadata.json"] = build_metadata()
    files["$themes.json"] = build_themes()
    return files


def build_bundle(files: dict[str, object]) -> dict:
    """Merge the per-set files into one object (first-level keys = set names),
    the single-file import shape for browser-based Figma."""
    return {fn[:-5]: content for fn, content in files.items()}


def _serialize(content: object) -> str:
    return json.dumps(content, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    check = "--check" in sys.argv
    files = render()
    bundle = build_bundle(files)
    if check:
        stale = [
            fn for fn, content in files.items()
            if not (OUT / fn).exists() or (OUT / fn).read_text() != _serialize(content)
        ]
        if not BUNDLE.exists() or BUNDLE.read_text() != _serialize(bundle):
            stale.append("../bundle.json")
        if stale:
            print(f"✗ Tokens Studio sidecar stale: {stale}. Run: python ops/gen_figma_sets.py")
            sys.exit(1)
        print("✓ Tokens Studio sidecar in sync with tokens.json")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for fn, content in files.items():
        (OUT / fn).write_text(_serialize(content))
    BUNDLE.write_text(_serialize(bundle))
    print(f"✓ wrote {len(files)} sidecar files + bundle.json → {OUT.parent.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
