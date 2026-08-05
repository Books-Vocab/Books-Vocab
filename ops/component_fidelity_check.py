#!/usr/bin/env -S uv run --python 3.13 python
"""component_fidelity_check — guard web component COMPOSITION against the iOS twins.

token_drift_check.py guards token VALUES (tokens.json ↔ iOS Swift literals). This
guards the NEXT layer: which token each hand-authored primitive in
design-system/dist/kg-components.css SELECTS. That .kg-chip is a Capsule pill with
the AppTag fill, .kg-btn uses AppRadius.md, the serif headings render at iOS's
isBold 700 — none of which token_drift can see, because every individual token value
is correct; the bug is picking the WRONG token. The historical chip-6px bug and the
button-radius / heading-weight / input / banner drifts all lived here, invisible.

This file is the component-layer SoT + its regression guard. Each CONTRACT entry
pins one CSS declaration of one primitive to the token its iOS twin uses, with the
iOS provenance in the comment. A mismatch = composition drift = exit 1.

Verification chain (honest boundary):
  CSS uses token X            ← THIS check (contract ↔ kg-components.css)
  token X value = iOS literal ← token_drift_check.py
  iOS twin uses token X       ← human-reviewed + audit-verified (documented per entry);
                                SwiftUI body composition is not auto-parsed.

Run:  uv run --python 3.13 python ops/component_fidelity_check.py
Exit: 0 = all primitives conform, 1 = drift.
Env override (tests): KG_COMPONENTS_CSS.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPONENTS = Path(os.environ.get(
    "KG_COMPONENTS_CSS", REPO / "design-system" / "dist" / "kg-components.css"))

# selector -> {css-property: exact-expected-value}. Provenance = the iOS element mirrored.
CONTRACT: dict[str, dict[str, str]] = {
    # chip ↔ iOS AppTag (AppSurface.swift:80-94 + AppTagMetrics): Capsule pill, caption,
    # tone@0.08/0.18 fill, 10×5 padding.
    ".kg-chip": {
        "font-size": "var(--text-caption)",
        "background": "var(--tag-fill)",
        "padding": "var(--chip-padding-v) var(--chip-padding-h)",
        "border-radius": "var(--radius-pill)",
    },
    # card ↔ iOS AppSectionCardStyle / ListSectionCard (vocab card): md(8) radius,
    # cardBorder×0.7 resting hairline, z1 resting.
    ".kg-card": {
        "border-radius": "var(--radius-card)",
        "box-shadow": "var(--elevation-z1)",
        "padding": "var(--card-padding)",
    },
    # button ↔ iOS AppActionButtonStyle: AppRoundness.control（46pt 高 → r≈6.9；web 側維持絕對 8px）, subhead, .semibold (→700 on web,
    # ElmsSans ships 400/700 only). Press feedback intentionally uses the shared web
    # TapFeedback triplet (北極星 5 motion convergence), NOT AppActionButtonStyle's bespoke
    # 0.992/0.82 — so it is NOT pinned here.
    ".kg-btn": {
        "border-radius": "var(--radius-md)",
        "font-size": "var(--text-subhead)",
        "font-weight": "700",
    },
    # primary CTA ↔ web brand-hero strategy (北極星 4 單一強調色). INTENTIONALLY diverges from
    # iOS AppActionButtonStyle.primary (neutral primaryText fill) — pinned so the奶黃 CTA
    # cannot silently regress to a neutral fill.
    ".kg-btn--primary": {
        "background": "var(--brand-hero)",
        "color": "var(--on-brand-hero)",
    },
    # input ↔ iOS AppSearchField (themed variant): body(17) text + visible resting cardBorder
    # hairline. background pins the web --stage-bg recessed-surface choice (iOS themed uses
    # cardBackground — a deliberate web divergence, locked here so it cannot silently regress).
    ".kg-input": {
        "font-size": "var(--text-body)",
        "border": "var(--sp-hairline) solid var(--card-border)",
        "background": "var(--stage-bg)",
        "border-radius": "var(--radius-control)",
    },
    # banner ↔ iOS AppBanner text metrics: caption(12), vertical 8 (AppBannerMetrics).
    # border-radius is web-inline-card shape (iOS AppBanner is a full-width bottom-border
    # bar) — an intentional surface-context divergence, pinned to its web value.
    ".kg-banner": {
        "font-size": "var(--text-caption)",
        "padding": "var(--sp-2) var(--sp-4)",
        "border-radius": "var(--radius-card)",
    },
    # serif headings ↔ iOS isBold collapse → Athelas-Bold 700 (hero .semibold / h1·h2 .medium
    # all render bold; AppSkin.sectionTitle bold=700 + backend site.css corroborate). hero
    # ships untracked (Tracking.tight is defined but applied at zero call sites on iOS).
    ".kg-hero": {"font-weight": "700", "font-family": "var(--font-serif)"},
    ".kg-h1": {"font-weight": "700", "font-family": "var(--font-serif)"},
    ".kg-h2": {"font-weight": "700", "font-family": "var(--font-serif)"},
    # link ↔ iOS accent-coloured link.
    ".kg-link": {"color": "var(--accent)"},
}


def parse_css(src: str) -> dict[str, dict[str, str]]:
    """Flat CSS → {selector: {property: value}}. Strips comments + @media blocks first."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"@media[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", src, flags=re.S)
    rules: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", src):
        selectors = [s.strip() for s in m.group(1).split(",") if s.strip()]
        decls: dict[str, str] = {}
        for d in m.group(2).split(";"):
            if ":" in d:
                prop, val = d.split(":", 1)
                decls[prop.strip()] = re.sub(r"\s+", " ", val.strip())
        for sel in selectors:
            rules.setdefault(sel, {}).update(decls)
    return rules


def check() -> list[str]:
    css = parse_css(COMPONENTS.read_text(encoding="utf-8"))
    errors: list[str] = []
    for sel, props in CONTRACT.items():
        if sel not in css:
            errors.append(f"{sel}: selector not found in kg-components.css")
            continue
        for prop, expected in props.items():
            got = css[sel].get(prop)
            if got is None:
                errors.append(f"{sel} {{ {prop} }}: missing (contract expects '{expected}')")
            elif got != expected:
                errors.append(f"{sel} {{ {prop} }}: '{got}' != contract '{expected}'")
    return errors


def main() -> int:
    errors = check()
    if errors:
        print(f"❌ component fidelity: {len(errors)} primitive declaration(s) drifted "
              "from the iOS-aligned contract\n")
        for e in errors:
            print(f"  - {e}")
        print("\nFix: align design-system/dist/kg-components.css to the CONTRACT, or — if iOS "
              "itself changed — update the CONTRACT + its provenance note in this file.")
        return 1
    n = sum(len(v) for v in CONTRACT.values())
    print(f"✅ component fidelity: {len(CONTRACT)} primitives / {n} pinned declarations "
          "conform to the iOS-aligned contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
