# Vocabulary UI Architecture

This folder is organized by responsibility so UI refactors can stay local.

## Entry Points

- `VocabularyListView.swift`
  - Top-level vocabulary tab container.
  - Chooses between local vocab, KG vocab, and graph views.
- `Scenes/KGVocabView.swift`
  - KG vocabulary browser scene.
  - Owns list state, session entry, and sync-driven browsing UI.
- `Scenes/TodayReviewView.swift`
  - Review session scene only.
  - Owns flip-card flow, review actions, and linked-card overlay entry.
- `Scenes/WordDetailSheet.swift`
  - Detail scene only.
  - Owns section composition and linked-card overlay entry.

## Shared Layers

- `Presentation/CardPresentation.swift`
  - Converts `VocabularyEntry` into UI-facing card data.
  - Central place for examples, forms, metadata, and grouped links.
- `Overlay/LinkedCardOverlayStack.swift`
  - Shared stacked linked-card modal flow.
  - Used by both review and detail scenes.
- `Components/CardRichTextRenderer.swift`
  - Shared example/note text rendering.
  - Handles highlight and cloze formatting.
- `Components/WordDetailComponents.swift`
  - Reusable detail-scene building blocks.

## Other Views

- `KnowledgeGraphView.swift`
  - Dedicated graph explorer scene.
- `GraphWebView.swift`
  - Graph rendering bridge.
- `SyncView.swift`
  - Sync operations scene.

## Refactor Guidance

- If you want to change card data shape, start in `Presentation/`.
- If you want to change linked-card interaction, start in `Overlay/`.
- If you want to redesign review UI, start in `Scenes/TodayReviewView.swift`.
- If you want to redesign detail UI, start in `Scenes/WordDetailSheet.swift` and `Components/WordDetailComponents.swift`.
- Avoid recomputing card-specific presentation inside scenes. Add it to `CardPresentation` first.
