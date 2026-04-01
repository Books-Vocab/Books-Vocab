# TipKit Contextual Onboarding Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3 contextual TipKit tips to guide new users through core interactions: long-press word lookup, vocabulary sync, and EPUB sourcing.

**Architecture:** Single `AppTips.swift` file defines all tips. `BooksBrowserApp` configures TipKit. Each tip is donated/invalidated at the relevant coordinator layer. Tips are inline or popover, using system default styling.

**Tech Stack:** iOS 17 TipKit framework, SwiftUI

**Spec:** `docs/superpowers/specs/2026-03-22-tipkit-onboarding-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `ios/BooksBrowser/Models/AppTips.swift` | All 3 tip definitions with events and rules |
| Modify | `ios/BooksBrowser/BooksBrowserApp.swift:170` | `Tips.configure()` in `.task {}` |
| Modify | `ios/BooksBrowser/Views/Reader/ReaderTranslationHandler+Flows.swift:90` | Donate `wordLookedUp` + invalidate LongPressTip |
| Modify | `ios/BooksBrowser/Views/Reader/ReaderView.swift` | Display LongPressTip popover |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncCoordinator.swift:235` | Donate `syncCompleted` + invalidate SyncPendingTip |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:44` | Display SyncPendingTip inline + pending query |
| Modify | `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift:109` | Display EPUBGuideTip inline |
| Modify | `ios/BooksBrowser/Views/Bookshelf/BookshelfCoordinator.swift:101` | Invalidate EPUBGuideTip on import |

---

## Task 1: Define Tips + Configure TipKit

**Files:**
- Create: `ios/BooksBrowser/Models/AppTips.swift`
- Modify: `ios/BooksBrowser/BooksBrowserApp.swift:170`

- [ ] **Step 1: Create AppTips.swift**

```swift
import SwiftUI
import TipKit

// MARK: - Long Press Word Lookup

struct LongPressTip: Tip {
    static let wordLookedUp = Event(id: "wordLookedUp")

    var title: Text { Text("長按查詞") }
    var message: Text? { Text("長按任何單字即可查詢 AI 翻譯與詞性解析") }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var rules: [Rule] {
        #Rule(Self.wordLookedUp) { $0.donations.count == 0 }
    }
}

// MARK: - Sync Pending Vocabulary

struct SyncPendingTip: Tip {
    static let syncCompleted = Event(id: "syncCompleted")

    var title: Text { Text("同步你的單字") }
    var message: Text? { Text("你有未同步的生詞，點擊同步按鈕推送到雲端") }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var rules: [Rule] {
        #Rule(Self.syncCompleted) { $0.donations.count == 0 }
    }
}

// MARK: - EPUB Guide

struct EPUBGuideTip: Tip {
    var title: Text { Text("哪裡找電子書？") }
    var message: Text? { Text("查看 EPUB 取得指南，了解如何取得免費或付費電子書") }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var actions: [Action] {
        [Action(id: "查看指南", title: "查看指南")]
    }
}
```

- [ ] **Step 2: Add TipKit configuration to BooksBrowserApp**

In `BooksBrowserApp.swift`, after the existing `.onOpenURL` handler (around L170), add a new `.task {}`:

```swift
.task {
    try? await Tips.configure()
}
```

Add `import TipKit` at the top of the file.

- [ ] **Step 3: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Models/AppTips.swift
git add ios/BooksBrowser/BooksBrowserApp.swift
git commit -m "ios: add TipKit tip definitions and configure in app startup"
```

---

## Task 2: LongPressTip — Reader Word Lookup

**Files:**
- Modify: `ios/BooksBrowser/Views/Reader/ReaderTranslationHandler+Flows.swift:90`
- Modify: `ios/BooksBrowser/Views/Reader/ReaderView.swift`

- [ ] **Step 1: Donate event on word lookup success**

In `ReaderTranslationHandler+Flows.swift`, find the `autoSaveToVocabulary` call (around L90). After this call, add the donation and invalidation:

```swift
// After autoSaveToVocabulary(...) call:
LongPressTip.wordLookedUp.donate()
LongPressTip().invalidate(reason: .actionPerformed)
```

Add `import TipKit` at the top of the file.

- [ ] **Step 2: Display tip in ReaderView**

In `ReaderView.swift`, the body returns a `ReaderViewPresenter(...)` (L62-76). Add a `.safeAreaInset(edge: .top)` to the `ReaderViewPresenter` to show the tip at the top of the reader without overlapping content:

```swift
ReaderViewPresenter(
    // ... existing parameters ...
) { ... }
.safeAreaInset(edge: .top) {
    TipView(LongPressTip())
        .padding(.horizontal)
}
.tint(.secondary)
// ... rest of existing modifiers
```

Place the `.safeAreaInset` BEFORE `.tint(.secondary)` (L77). This keeps the tip above the reading area without blocking text.

Add `import TipKit` at the top.

- [ ] **Step 3: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Reader/ReaderTranslationHandler+Flows.swift
git add ios/BooksBrowser/Views/Reader/ReaderView.swift
git commit -m "ios: add LongPressTip for reader word lookup onboarding"
```

---

## Task 3: SyncPendingTip — Vocabulary Sync Reminder

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncCoordinator.swift:235`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:44`

- [ ] **Step 1: Donate event on sync completion**

In `SyncCoordinator.swift`, find where `phase = .completed` is set (around L235). After this line, add:

```swift
SyncPendingTip.syncCompleted.donate()
SyncPendingTip().invalidate(reason: .actionPerformed)
```

Add `import TipKit` at the top.

- [ ] **Step 2: Add pending query and inline tip to NotebookListView**

In `NotebookListView.swift`, add a `@Query` for pending entries and display the tip conditionally.

**Important:** `NotebookListView` has a custom `init()`. You cannot declare `@Query(filter:)` as a stored property with inline predicate when a custom `init()` exists — the compiler will require it to be initialized in `init()`. Instead, initialize it in the `init()` body using the underscore syntax:

```swift
// Add as a stored property (no inline filter):
@Query private var pendingEntries: [VocabularyEntry]

// In the existing init(), add:
_pendingEntries = Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != 1 && $0.actionType != "delete" })
```

Read the existing `init()` to see where to insert the `_pendingEntries` assignment.

In the `body`, at the top of the `LazyVStack` (around L44, before the `reviewBanner` section), add:

```swift
if !pendingEntries.isEmpty {
    TipView(SyncPendingTip())
        .padding(.horizontal, skin.spacing.listRowHorizontalInset)
        .padding(.bottom, skin.spacing.sectionGap)
}
```

Add `import TipKit` at the top.

- [ ] **Step 3: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/SyncCoordinator.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift
git commit -m "ios: add SyncPendingTip for vocabulary sync onboarding"
```

---

## Task 4: EPUBGuideTip — Where to Find Books

**Files:**
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift:109`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfCoordinator.swift:101`

- [ ] **Step 1: Add inline tip to bookshelf empty state**

In `BookshelfView.swift`, find the `emptyState` computed property (around L97-L138). After the `AppEmptyStateContent` and before the `Button("匯入")` (around L109), insert:

```swift
TipView(EPUBGuideTip()) { action in
    if action.id == "查看指南" {
        openURL(AppURLs.guide)
    }
}
.padding(.horizontal)
```

Make sure `@Environment(\.openURL) private var openURL` is available in the view (add if not present).

Add `import TipKit` at the top.

- [ ] **Step 2: Invalidate tip on successful book import**

In `BookshelfCoordinator.swift`, find where the import completes successfully — after `modelContext.safeSave()` (around L101). Add:

```swift
EPUBGuideTip().invalidate(reason: .actionPerformed)
```

Add `import TipKit` at the top.

- [ ] **Step 3: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift
git add ios/BooksBrowser/Views/Bookshelf/BookshelfCoordinator.swift
git commit -m "ios: add EPUBGuideTip for book sourcing in empty bookshelf"
```

---

## Task 5: Final Build + Smoke Test

- [ ] **Step 1: Full build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 2: Manual smoke test**

Test in simulator (reset TipKit data with `Tips.resetDatastore()` if needed):

1. Launch app fresh → Welcome carousel → enter main screen
2. Open an empty bookshelf → EPUBGuideTip should appear with "查看指南" action
3. Import an EPUB → EPUBGuideTip should disappear permanently
4. Open the book → LongPressTip should appear ("長按查詞")
5. Long-press a word → translation panel appears → LongPressTip disappears permanently
6. Navigate to Notebook tab → if pending words exist, SyncPendingTip appears
7. Complete a sync → SyncPendingTip disappears permanently
8. Re-navigate to all locations → no tips reappear

- [ ] **Step 3: Commit any fixes**
