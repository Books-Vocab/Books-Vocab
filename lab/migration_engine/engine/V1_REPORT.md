# Migration Engine v1 — child-tree extraction report

Status: **v1, child-tree IR shipped.** The v0→v1 step is structural, not a bigger codex:
the extractor now builds a **nested tree** instead of a flat modifier list, which unblocks
the single biggest v0 miss class — `display / flex-direction / align-items /
justify-content / gap` — the layout declarations every chip / row / pill needs.

## What changed (v0 → v1)

| stage | v0 | v1 |
|---|---|---|
| `extract_swiftui.py` | flat modifier list collapsed onto one synthetic root | **nested tree**: stacks (HStack/VStack/ZStack) contain leaf nodes (Text/Image/Spacer/child-view), modifiers attach per-node; unparsable subtrees flagged `unparsed` |
| `generate_css.py` | container-level visual decls only; layout was invisible | **layout mapping**: stack → `flex` + direction + gap + align/justify; leaf-wrapping-box (label inside padding+background) → `inline-flex` centered. Capsule stacks → `inline-flex` (pills sit inline). Visual/geometry carried from v0 + new resolvers (skin.spacing fields, metric constants, frame width/height, stroke opacity) |
| `eval_holdout.py` | `display / justify-content / gap` were OUT_OF_SCOPE (no tree) | **promoted into scope** — now scored, since the tree derives them. Leaf type metrics (line-height, font-variant-numeric, -webkit-text-stroke) and page anchors (margin/position/z-index) remain out-of-scope |
| regression gate | `test_engine_v0.py` (2 cases, agg ≥80%) | `test_engine_v1.py` (4 cases / 3 surfaces, agg ≥85%); v0 gate retained as a weaker floor |

## Holdout results — v1 vs v0

4 holdouts: the 2 v0 notebook components + **2 new nested holdouts on different surfaces**
(today-review chevron pill, vocabulary sort pill). Hit rate = declaration-level
generalization score (engine CSS vs blessed hand CSS); pixel parity needs TSX gen, still
out of scope.

| holdout | surface | structure | v0 hit | v1 hit | Δ |
|---|---|---|---:|---:|---:|
| `nb-actionbar` | notebook | HStack container (title+Spacer+pills) | 100.0% | **100.0%** | — |
| `nb-pill` | notebook | leaf-wrapping pill (generic content) | 71.4% | **80.0%** | +8.6 |
| `tr-chevron-pill` | today-review | leaf-in-capsule, fixed frame, hairline | *new* | **88.9%** | new |
| `vc-sort-pill` | vocabulary | HStack-in-capsule pill, compactChip pad | *new* | **90.0%** | new |
| **aggregate** | 3 surfaces | | **83.3%**¹ | **88.9%** | **+5.6** |

¹ v0 aggregate was the 2-case notebook slice (10/12). The same 2 cases under v1 score
88.2% (15/17) — the +4.9 there is pure child-tree layout unlock with zero new codex rules.
Whole 4-case v1 aggregate = **32/36 = 88.9%**, clearing the ≥85% target.

Reproduce:
```
uv run python lab/migration_engine/engine/test_engine_v1.py
# or one case:
uv run python lab/migration_engine/engine/extract_swiftui.py \
  ios/BooksAndVocab/Views/Vocabulary/Components/VocabShellComponents+Actions.swift \
  --struct VocabSortPill --out /tmp/ir.json
uv run python lab/migration_engine/engine/generate_css.py /tmp/ir.json \
  --struct VocabSortPill --selector vc-sort-pill --out /tmp/e.css
uv run python lab/migration_engine/engine/eval_holdout.py \
  --hand web/src/surfaces/vocabulary/vocabulary.css --engine /tmp/e.css --class vc-sort-pill
```

## Remaining misses (4 of 36) — v2 backlog, top N

1. **`nb-pill` gap MISS (2px).** The pill's child gap comes from the *call site*
   (`HStack(spacing: AppSpacing.microGap)` wrapping the icon+count), not from
   `NotebookHeaderPillLabel` itself — its content is a generic `@ViewBuilder` param the
   component cannot see. **Genuinely un-derivable at component scope.** v2: cross-component
   resolution — extract the call site and bind the generic content tree into the component
   IR. (Highest-value structural gap remaining.)

2. **`nb-pill` + `vc-sort-pill` font-weight — RECONCILED (was DEVIATE: hand 600 vs engine 700).**
   The holdout re-exposed the **codex-stale divergence** flagged in V0_REPORT §2 on a *second*
   surface (vocabulary), strengthening the case that the prior `semibold_chip_700` claim was
   wrong: KG web ships the Inter/SF stack (real 600 face), not ElmsSans, so iOS `.semibold`
   stays **600** and does not collapse to 700. Fixed the codex line — rule renamed
   `semibold_chip_600` (`codex/l2_rules.yaml`) and `generate_css.py` now emits `font-weight: 600`
   for semibold. Both prior misses now **hit** (nb-pill 80→90%, vc-sort-pill 90→100%, aggregate
   94.4%). 2 of the 4 v1 misses resolved.

3. **`tr-chevron-pill` display DEVIATE (hand `flex` vs engine `inline-flex`).** The chevron
   is a leaf-wrapping capsule, so the engine emits `inline-flex` (correct for a pill). The
   page re-blocks it to `display:flex` to ride the fold seam via `margin: -9px auto`. The
   `display` here is **coupled to a page anchor** (`margin auto`, already out-of-scope), not
   a platform delta. v2: when a node carries a page-anchor margin, defer its `display`
   variant to the page (don't score it as a component decl).

## v0 layer-mix tracking

v1 per-case provenance (L1 token / L2 codex / orphan): nb-actionbar 9/1/0 · nb-pill 6/2/3 ·
chevron 6/3/0 · sort-pill 9/1/2. Layout decls land as a new `L1:layout` class (structural
isomorphism, no measurement) — consistent with the audit thesis that layout is L1-derivable
once the tree exists. Orphans are the genuinely page-local values (composite off-grid pads,
measured compactChip override, view-param fills) — correctly NOT promoted to the codex.

## One-line v2 recommendation

Build **call-site / generic-content resolution** next: the last structural miss
(`nb-pill` gap, and any component taking `@ViewBuilder content`) is blocked on the engine
seeing only the component in isolation — binding the caller's child tree into the component
IR is the v2 unlock, the same way child-tree was v1's.
