# iOS→Web Migration Engine — skeleton proposal (v1)

Goal: distill the hand-aligned 63-case parity rewrite into a **reusable transducer**
so the *next* surface is generated engine-first, then corrected only by residual,
instead of re-measured pixel-by-pixel from scratch.

This doc is the architecture contract; it does not ship code yet. It is grounded in
the audit (`../audit/report.md`): **70% token / 18% L2 / 12% orphan**. Those three
numbers ARE the three layers.

```
  SwiftUI view source  ──┐
  DesignTokens.swift   ──┤
  tokens.json (SoT)    ──┴──►  [L1 deterministic mapper]
                                      │  emits CSS/TSX draft using ONLY tokens
                                      ▼
                               [L2 codex applier]  ◄── codex/l2_rules.yaml
                                      │  rewrites non-isomorphic deltas (token+delta)
                                      ▼
                               CSS + TSX draft  (engine-first surface)
                                      │
                                      ▼
                               [L3 oracle loop]  ◄── web_parity.sh (rig as fitness fn)
                                      │  capture → diff vs iOS Catalog → residual
                                      └──► residual feeds back: new L2 rule? page anchor? overfit?
```

## L1 — deterministic mapper (the 70%)

Pure mechanical SwiftUI↔CSS isomorphism. No measurement. Inputs: the SwiftUI view
AST (or a structured extraction of it) + the token tables.

Mappings (all reversible, all token-preserving):

| SwiftUI | CSS | note |
|---|---|---|
| `VStack(spacing: s)` | `display:flex; flex-direction:column; gap: <token(s)>` | spacing→gap |
| `HStack(spacing: s)` | `flex-direction:row; gap: <token(s)>` | |
| `.padding(.all, p)` | `padding: <token(p)>` | pt→px via `pt_equals_px` |
| `.padding(.horizontal, p)` | `padding-inline: <token(p)>` | |
| `AppSpacing.s4` etc. | `var(--sp-4)` | scalar group already bridged in DesignTokens.swift |
| `AppRadius.md` | `var(--radius-md)` | |
| `.font(AppFonts.body)` | `font-size: var(--text-body); line-height: var(--leading-body)` | |
| `Color tokens` | `var(--<color-token>)` | theme handled by `[data-theme]` |
| `Spacer()` | `flex: 1` / `margin-*: auto` | |
| `RoundedRectangle(cornerRadius:)` | `border-radius: <token>` | |

The mapper's job is to get a draft that is *correct wherever iOS and web agree*. The
token table is the shared vocabulary (`tokens.json` → DesignTokens.swift for iOS,
→ kg-tokens.css for web, already drift-guarded by `ops/token_drift_check.py`). Any
literal the mapper would emit that ISN'T a token is a signal to consult L2.

## L2 — platform-difference codex applier (the 18%)

Input: the L1 draft + `codex/l2_rules.yaml`. For each rule whose `applies_when`
predicate matches a node in the draft, rewrite the value as `token + named delta`
and emit the iOS intent as a comment (round-trip fidelity).

Each codex rule is `token + named delta`, never a bare magic number. Examples from
v1 (see the YAML for full provenance):

- `hairline_physical_px`: any iOS hairline → `0.34px` (= `--sp-hairline / dpr3`), not `1px`.
- `bold_weight_700_floor` / `semibold_chip_700`: iOS medium/semibold/bold → `font-weight:700`
  (ElmsSans ships 400/700 only; 600 would faux-bold and is rejected).
- `songti_bold_stroke_sim`: small dense serif CJK titles get `-webkit-text-stroke:0.5px`
  (Chromium can't load Songti Bold) — but NOT on large titles (counter-evidence logged).
- `large_title_nav_anchor`: large-title top = `118px` (= statusBar 59 + inlineBar 44 + rowInset 15).
- `uiswitch_on_solid_capsule`: native toggle → solid accent capsule, no knob.

**Codex admission gate**: a rule enters `rules:` only with provenance in ≥2 surfaces.
Single-surface measured values live in `candidates:` and the engine MUST NOT emit them
from the codex — they belong to the page. This is the anti-overfit wall at write time.

## L3 — oracle loop (the rig as fitness function)

The existing `ops/web_parity.sh` (+ `web/tools/shots.mjs` capture, `parity-core.mjs`
diff/RMSE/SSIM/pHash) is already a fitness function: it captures a web surface at the
Catalog resolution and diffs against the blessed iOS Catalog snapshot. The engine
closes the loop:

1. Engine emits surface draft (L1+L2).
2. Run `web_parity.sh --audit --only <surface>` → per-case RMSE + diff.png + residual map.
3. Triage the residual:
   - residual explained by an **existing L2 rule not yet applied** → fix the applier predicate.
   - residual is a **new systematic delta** seen on this surface AND ≥1 already-aligned
     surface → promote to a new L2 rule (cite both).
   - residual is **page-specific** (a measured anchor with no cross-surface twin) →
     write it into the surface CSS as an annotated orphan, NOT the codex.

The verdict gate reuses the parity RMSE thresholds already encoded per-case (the
0.016–0.135 band from the hand rewrite is the bar to match or beat).

## Anti-overfit mechanism — holdout generalization score

The orphan % (12%) is the engine's overfit budget. To measure whether the codex
*generalizes* rather than memorizes, run a **holdout**:

1. Pick one already-aligned surface S (e.g. `notebook`). Pretend it does not exist:
   exclude any codex rule whose provenance is *only* S.
2. Regenerate S engine-first from its SwiftUI source using the reduced codex.
3. Run `web_parity.sh --only S` on the engine output.
4. **Generalization score** = `RMSE(engine-S) − RMSE(hand-S)`.
   - ≈ 0 → the codex's cross-surface rules fully reconstruct S; no S-specific overfit.
   - large positive → S relied on rules that don't generalize; either S has genuine
     page anchors (acceptable, they go in surface CSS) or the codex is too thin.

Rotate the holdout across all 8 surfaces to get a generalization profile. A codex
rule that, when removed, only hurts its own origin surface is overfit by definition.

## Inputs / boundaries

- **In**: SwiftUI view source (structured extraction; start with a hand-written IR per
  surface, not a full Swift parser — the 8 surfaces are bounded), `tokens.json`,
  `DesignTokens.swift`, `codex/l2_rules.yaml`.
- **Out**: a `*.css` + `*.tsx` draft per surface, plus a residual report from L3.
- **Non-goals (v1)**: a general Swift AST parser; runtime behavior/interaction port
  (this is visual transduction only); replacing the hand surfaces (engine is additive —
  it generates drafts for *new* surfaces and is validated by reconstructing existing ones).

## Build order

1. L1 mapper over a hand-written IR for ONE surface (settings is densest) → token-only draft.
2. L2 applier consuming `l2_rules.yaml` → corrected draft.
3. Wire L3 = `web_parity.sh --only settings` as the gate; record RMSE delta vs hand.
4. Holdout-rotate to score generalization; grow the codex only via the L3 triage rule.
