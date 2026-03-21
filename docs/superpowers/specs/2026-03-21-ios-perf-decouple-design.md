# iOS Performance: Decouple Expensive Work from Main Thread

**Date:** 2026-03-21
**Scope:** Card expansion sheet + Translation completion path

## Problem

Two user-facing jank scenarios traced to main-thread blocking:

1. **Card expansion:** Sheet animation frames re-evaluate `presenterState` (computed property), each time running JSON decode, regex compile, and O(N×M) array scan.
2. **Translation completion:** Single MainActor continuation chains view diff → synchronous disk I/O → second animation → full vocabulary scan with no yield.

## Changes

### A. Card Expansion Path

#### A1. `VocabularyEntry.graphLinksByKind` — transient cache

- Add `@Transient var _cachedGraphLinks: [String: [KGCardLinkSummary]]?`
- First `get`: decode and cache. Subsequent: return cache.
- `set`: encode + clear cache.

**File:** `ios/BooksBrowser/Models/VocabularyEntry.swift`

#### A2. `markWordInContext()` — cache compiled regex

- Add `private static let regexCache = NSCache<NSString, NSRegularExpression>()`
- Before `NSRegularExpression(pattern:)`, check cache. After compile, store in cache.

**File:** `ios/BooksBrowser/Models/VocabularyEntry.swift`

#### A3. Link lookup — dictionary instead of linear scan

- In `WordDetailPresentation.state()` caller, build `[String: VocabularyEntry]` keyed by `kgCardId` once.
- Pass dictionary into state builder. Replace `allEntries.first { ... }` with dict lookup.

**Files:** `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`, `ios/BooksBrowser/Views/Vocabulary/Presentation/WordDetailPresentation.swift`

#### A4. `WordDetailSheet.presenterState` — compute once in .task

- Change from computed property to `@State private var state: WordDetailPresenterState?`
- Compute in `.task { state = WordDetailPresentation.state(...) }`
- Show `ProgressView` until state is ready (sub-frame delay, not user-visible).

**File:** `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift` (or wherever the sheet struct lives)

### B. Translation Completion Path

#### B1. `autoSaveToVocabulary` disk I/O — background ModelContext

- Create a new `ModelContext(modelContainer)` off MainActor.
- Insert + save on cooperative thread pool (non-`@MainActor` async function or `Task.detached`).
- Notify main thread only after save completes (set `isSaved = true`).

**File:** `ios/BooksBrowser/Views/Reader/ReaderTranslationHandler+Persistence.swift`

#### B2. Yield between animation and save

- After `withAnimation { translationResult = result; isTranslating = false }`, add `await Task.yield()`.
- This lets SwiftUI complete the first diff/animation frame before autoSave runs.

**File:** `ios/BooksBrowser/Views/Reader/ReaderTranslationHandler+Flows.swift`

### Not In Scope

- Timer 100ms refactor (independent issue)
- `@Query` full-table loads (data volume issue, separate effort)
- Architecture changes or unrelated refactoring

## Verification

- Build with `./ops/ios_build.sh` — must pass
- Manual test: open card detail, confirm no visible delay
- Manual test: translate a word in reader, confirm smooth animation transition
- No existing tests should break
