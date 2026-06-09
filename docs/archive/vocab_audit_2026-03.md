<!-- doc-meta
tier: archive
authority: frozen
update_trigger: none
scope:
  - ios/BooksAndVocab/Views/Vocabulary/
verified_against: frozen
-->
# Vocab Design System Audit

Date: 2026-03-09
Scope: `ios/BooksAndVocab/Views/Vocabulary`, reader vocab panel integration, shared shell dependencies

## Current Assessment

- Coverage: high
- Reuse: medium-high
- Soundness: medium

The current vocab design system is a real feature-level UI system centered on `VocabSkin`, not a loose collection of styles. It already controls most vocabulary flows, including list, review, sync, detail sheet, and graph theming. The main gaps are semantic completeness, layout token coverage, and verification.

## What Is Working

- Single token entry point exists in [ios/BooksAndVocab/Views/Vocabulary/Skin/VocabSkin.swift](../ios/BooksAndVocab/Views/Vocabulary/Skin/VocabSkin.swift).
- App-level injection exists in [ios/BooksAndVocab/Models/AppTheme.swift](../ios/BooksAndVocab/Models/AppTheme.swift) via `AppThemeContainer`.
- Reader explicitly re-injects vocab skin for vocab-mode panels in [ios/BooksAndVocab/Views/Reader/ReaderView.swift](../ios/BooksAndVocab/Views/Reader/ReaderView.swift).
- Shared shell reuse is good. Cards, empty states, toolbar glyphs, tab selector, search field, and key-value rows all bridge through [ios/BooksAndVocab/UIComponents/AppShellComponents.swift](../ios/BooksAndVocab/UIComponents/AppShellComponents.swift).
- Presentation-level graph theming is wired to the same skin in [ios/BooksAndVocab/Views/Vocabulary/Presentation/KnowledgeGraphPresentation.swift](../ios/BooksAndVocab/Views/Vocabulary/Presentation/KnowledgeGraphPresentation.swift).

## Gaps

### P0: Missing Semantic Tokens

Problem:
- `warning` and `retry` states are borrowing difficulty tier colors instead of using dedicated semantic tokens.
- This couples learning semantics to system-status semantics.

Evidence:
- `tierColor(for:)` is used as warning/retry color in:
  - [ios/BooksAndVocab/Views/Vocabulary/Components/WordRow.swift](../ios/BooksAndVocab/Views/Vocabulary/Components/WordRow.swift)
  - [ios/BooksAndVocab/Views/Vocabulary/Scenes/PendingVocabPresenter.swift](../ios/BooksAndVocab/Views/Vocabulary/Scenes/PendingVocabPresenter.swift)
  - [ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncPresenter.swift](../ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncPresenter.swift)
  - [ios/BooksAndVocab/Views/Vocabulary/Components/VocabShellComponents.swift](../ios/BooksAndVocab/Views/Vocabulary/Components/VocabShellComponents.swift)

Impact:
- Hard to retune difficulty colors without affecting system messaging.
- Inconsistent meaning for the same color across screens.

Required fix:
- Add semantic palette tokens for:
  - `warning`
  - `retry`
  - `info`
  - optional: `overlayScrim`
- Restrict `tierColor(for:)` to difficulty/taxonomy-only use.

Acceptance:
- No non-difficulty UI state uses `tierColor(for:)`.

### P1: Layout Tokens Are Incomplete

Problem:
- Typography and color are centralized, but spacing, sizing, and layout rhythm are still partially hard-coded.
- Many views still use raw values such as `10`, `12`, `16`, `18`, `20`, `24`, `32`, `92`, `120`.

Representative files:
- [ios/BooksAndVocab/Views/Vocabulary/Scenes/TodayReviewPresenter.swift](../ios/BooksAndVocab/Views/Vocabulary/Scenes/TodayReviewPresenter.swift)
- [ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncPresenter.swift](../ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncPresenter.swift)
- [ios/BooksAndVocab/Views/Vocabulary/Scenes/KGVocabPresenter.swift](../ios/BooksAndVocab/Views/Vocabulary/Scenes/KGVocabPresenter.swift)
- [ios/BooksAndVocab/Views/Vocabulary/Scenes/PendingVocabPresenter.swift](../ios/BooksAndVocab/Views/Vocabulary/Scenes/PendingVocabPresenter.swift)

Impact:
- The system owns appearance but not composition rhythm.
- Visual drift will accumulate as more screens are added.

Required fix:
- Expand `VocabSkin.Spacing` and add size tokens, for example:
  - `pageHorizontalInset`
  - `pageVerticalInset`
  - `sectionSpacing`
  - `controlHeight`
  - `toolbarHeight`
  - `heroMinHeight`
  - `reviewCardMinHeight`
  - `overlayMaxWidth`
- Move repeated literal values behind semantic names.

Acceptance:
- Core vocab screens do not contain unexplained spacing literals except for isolated micro-adjustments.

### P1: Too Much Dependency on Global `AppMetrics`

Problem:
- Vocab screens still lean on global app metrics even when the visual language is feature-specific.

Impact:
- Global metric changes can unintentionally shift vocab layout.
- Makes vocab system less portable and harder to reason about.

Required fix:
- Decide which metrics stay global and which become vocab-local.
- Good default:
  - keep device/safe-area/page-shell metrics global
  - move feature rhythm and overlay dimensions into `VocabSkin`

Acceptance:
- `AppMetrics` use in vocab views is limited to app-shell concerns, not feature presentation rules.

### P1: Limited Isolation From `AppTheme`

Problem:
- `VocabSkin` is composed from `AppTheme`, so it behaves more like a derived skin than an independent token source.

Impact:
- Good for consistency, but weak for long-term autonomy.
- Harder to create alternate vocab themes or run targeted experiments.

Required fix:
- Make the layering explicit:
  - `AppTheme` owns app-wide semantic tokens
  - `VocabSkin` owns feature mapping plus feature-only tokens
- Document which tokens are inherited and which are vocab-only.

Acceptance:
- Engineers can answer whether a token belongs to app-wide semantics or vocab semantics without ambiguity.

### P2: Verification Is Thin

Problem:
- Shared shell has previews, but vocab feature screens do not appear to have a dedicated preview matrix, snapshot coverage, or UI contract tests.

Evidence:
- Shared shell preview exists in [ios/BooksAndVocab/UIComponents/AppShellComponents.swift](../ios/BooksAndVocab/UIComponents/AppShellComponents.swift).
- No vocab-specific preview/test matrix was found under `Views/Vocabulary`.

Impact:
- Refactors remain visually risky.
- Regressions will be caught manually, late, or not at all.

Required fix:
- Add preview coverage for:
  - `PendingVocabPresenter`
  - `KGVocabPresenter`
  - `WordDetailPresenter`
  - `SyncPresenter`
  - `TodayReviewPresenter`
  - `KnowledgeGraphPresenter`
- Add at least one lightweight UI contract test layer:
  - smoke render previews, snapshot tests, or deterministic screenshot tests

Acceptance:
- Every top-level vocab scene has at least one preview in light and dark.

### P2: Environment Usage Is Good but Not Universal

Observation:
- 14 vocab files directly read `@Environment(\.vocabSkin)`.
- Injection points found were limited to:
  - `AppThemeContainer`
  - reader root
  - reader settings panel branch

Risk:
- New entry points can easily forget skin injection if they bypass `AppThemeContainer`.

Required fix:
- Document the rule:
  - all vocab scenes must be mounted inside `AppThemeContainer` or explicitly apply `.vocabSkin(...)`
- Prefer higher-level composition roots over per-screen reinjection.

Acceptance:
- There is one documented composition rule and no ad hoc injection drift.

## Recommended Refactor Order

1. Add missing semantic tokens to `VocabSkin.Palette` and remove `tierColor(for:)` misuse.
2. Expand vocab-local layout tokens and replace repeated literals in top-level scenes.
3. Define token ownership boundaries between `AppTheme`, `VocabSkin`, and shared shell styles.
4. Add preview matrix for all top-level vocab scenes.
5. Add one automated visual or UI smoke layer.

## Suggested Implementation Plan

### Phase 1: Semantic Cleanup

- Extend `VocabSkin.Palette`.
- Replace warning/retry color lookups in `SyncPresenter`, `PendingVocabPresenter`, `WordRow`, and `VocabShellComponents`.
- Keep difficulty colors only for difficulty labels, graph tiers, and related taxonomy UI.

### Phase 2: Layout Tokenization

- Expand `VocabSkin.Spacing`.
- Add an optional `Metrics` sub-struct if spacing/radii are no longer enough.
- Refactor top-level presenters first, because they define the visible rhythm.

### Phase 3: Preview Matrix

- Add previews for each major scene using stable fixture states.
- Include empty, normal, and stressed variants where useful.

### Phase 4: Visual Guardrails

- Add snapshot tests or deterministic screenshot generation for:
  - list screen
  - detail sheet
  - review front/back/details
  - sync states
  - graph empty/settings states

## Success Criteria

- Vocab screens use semantic status tokens instead of difficulty tokens.
- Vocab screens rely on named layout tokens instead of repeated literals.
- Shared shell and vocab skin boundaries are documented and consistent.
- Every major vocab scene has preview coverage.
- At least one automated visual regression mechanism exists.
