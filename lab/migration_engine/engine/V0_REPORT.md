# Migration Engine v0 — end-to-end vertical slice report

Status: **v0 prototype, one thin vertical slice proven end-to-end.** Not a SwiftUI
parser; not pixel parity. The point is to show the L1→L2→L3 pipeline runs on real
source and to put an honest, measured number on "how much can the engine
auto-generate today".

## Pipeline (what was built)

```
SwiftUI view ──► extract_swiftui.py ──► IR JSON ──► generate_css.py ──► annotated CSS
                  (modifier-level)                   (L1 token · L2 codex)        │
                                                                                   ▼
                            hand surface CSS ◄── eval_holdout.py (declaration diff)
```

- `extract_swiftui.py` — regex + indent + balanced-paren line-join heuristic. Reduces
  a `View` struct body to a flat modifier list (padding / spacing / font(role) /
  foregroundStyle(token) / frame / cornerRadius / background fill+opacity / overlay
  stroke / Spacer). Anything it can't classify is emitted as `unmapped` (counted, not
  hidden).
- `generate_css.py` — **L1** maps symbolic names → css vars by name
  (`AppSpacing.s3`→`var(--sp-3)`, `AppRadius.lg`→`var(--radius-lg)`,
  `palette.primaryText`→`var(--text-primary)`, font role → family/size). **L2** applies
  `codex/l2_rules.yaml`: weight collapse (`.semibold/.bold`→700), `pt_equals_px`
  literals, hairline. Every output line is tagged `/* L1:token */`, `/* L2:<rule> */`,
  or `/* orphan */`.
- `eval_holdout.py` — declaration-level diff vs the blessed hand CSS. v0 generalization
  score = **declaration hit rate** (pixel parity needs TSX structure gen, out of scope).
  Folds var↔px and padding shorthand↔longhand so notation differences aren't false
  deviations.
- `test_engine_v0.py` — pins the hit-rate floor (regression gate).

## Holdout target

Surface: **notebook** (already hand-aligned, so it's a valid oracle). Slice: the two
self-contained container components whose SwiftUI source maps 1:1 to hand CSS classes:

| SwiftUI struct | hand class | hit rate | L1 | L2 | orphan |
|---|---|---:|---:|---:|---:|
| `NotebookReviewActionBar` | `.nb-actionbar` | **100.0%** (5/5) | 12 | 3 | 0 |
| `NotebookHeaderPillLabel` | `.nb-pill` | **71.4%** (5/7) | 3 | 2 | 3 |
| **aggregate** | | **83.3%** (10/12) | 15 | 5 | 3 |

Reproduce:
```
uv run python lab/migration_engine/engine/extract_swiftui.py \
  ios/BooksAndVocab/Views/Vocabulary/Components/NotebookReviewActionBar.swift --out /tmp/ir.json
uv run python lab/migration_engine/engine/generate_css.py /tmp/ir.json --selector nb-actionbar --out /tmp/e.css
uv run python lab/migration_engine/engine/eval_holdout.py \
  --hand web/src/surfaces/notebook/notebook.css --engine /tmp/e.css --class nb-actionbar
# or just: uv run python lab/migration_engine/engine/test_engine_v0.py
```

## What the engine auto-generates today (estimate)

On *container-level layout/visual* declarations (the slice's scope), the engine
reconstructs **~83%** with zero hand-measurement, and **100%** on a pure-token
container (`.nb-actionbar`). Cross-checking against the audit split (70% token / 18%
L2 / 12% orphan): the slice shows **15 L1 + 5 L2 + 3 orphan = 65%/22%/13%**, closely
tracking the audit's predicted layer mix — evidence the three numbers really are the
three layers, and that a container slice is representative.

Honest scope caveat: this measures *container* declarations. Leaf-level type metrics
(line-height, font-variant-numeric, child gap) need the element tree that v0 does not
build — they are excluded from the scored denominator and listed as out-of-scope, not
counted as wins.

## Miss / deviation taxonomy (= v1 backlog, top N)

1. **align-items on inline-flex leaves (MISS)** — `.nb-pill` centers its content via
   `display:inline-flex; align-items:center; justify-content:center`. The v0 root
   element has no child tree, so it can't infer that a label-wrapping container needs
   inline-flex centering. **v1: child-tree extraction + a "pill/chip wrapper" L1
   pattern that emits inline-flex centering.** (highest-value, recurs on every chip.)

2. **font-weight 600 vs codex 700 (DEVIATE) — and it's a real codex-drift find.**
   `.nb-pill` hand CSS is `font-weight: 600`, but `codex/l2_rules.yaml`
   `semibold_chip_700` (provenance `notebook.css:87`) says iOS 600 → web **700**. The
   provenance line is **stale**: line 87 is now `600`, not 700. The engine applied the
   law faithfully and the holdout exposed the surface/codex divergence — exactly the
   anti-overfit signal the L3 loop is for. **v1: reconcile — either fix the hand
   surface to 700 (codex is law) or demote the rule; re-derive provenance lines.**

3. **Composite padding offsets land as `orphan` (3 in `.nb-pill`)** — `AppSpacing.s2 + 2`
   and `AppSpacing.s2 - AppSpacing.hairline` resolve numerically to the correct
   `10px`/`7px` (verified equal to the hand values — they still *hit*), but they're
   tagged `orphan` because the offset is off the token grid. **v1: a codex
   `off_grid_pad` rule family OR keep as annotated orphans (they're page-local, which
   per DESIGN.md is the correct home — this may not need promotion).** Also: the
   `view-param fill/foreground` (caller-supplied `fillColor`/`foregroundColor`) are
   correctly un-resolvable at the component level and belong to the call site.

## One-line v1 recommendation

Build **child-tree extraction** next (not a bigger codex): the single biggest miss
class — inline-flex leaf centering, leaf type metrics, child gap — is all blocked on
the flat-IR limitation, and unlocking it is what moves the slice from container-level
83% toward whole-surface coverage.
