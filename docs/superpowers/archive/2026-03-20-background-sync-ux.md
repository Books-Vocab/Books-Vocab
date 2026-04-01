# Background Sync UX Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `SyncCoordinator` to app-level so sync survives sheet dismissal and navigation, and show a spinning toolbar indicator while sync runs.

**Architecture:** `SyncCoordinator` moves from `@State` in `SyncView` to a `let` property in `BooksBrowserApp`, injected via a new `\.syncCoordinator` EnvironmentKey. `SyncView` reads from environment instead of owning the coordinator. The toolbar receives an `isSyncing` prop and a spinning icon when active. The sheet close button is always visible; a description line tells users sync continues after dismissal.

**Tech Stack:** Swift, SwiftUI, `@Observable`, `EnvironmentKey`, SF Symbols `.symbolEffect(.rotate, isActive:)`

**Spec:** `docs/superpowers/specs/2026-03-20-background-sync-ux-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `ios/BooksBrowser/Services/AppEnvironment.swift` | Modify | Add `SyncCoordinatorKey` + `\.syncCoordinator` |
| `ios/BooksBrowser/BooksBrowserApp.swift` | Modify | Create `syncCoordinator` property, inject into root view |
| `ios/BooksBrowser/Views/Vocabulary/SyncView.swift` | Modify | Switch from `@State` to `@Environment`, fix `.task` |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter.swift` | Modify | Show "關閉" at all phases |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter+Header.swift` | Modify | Add description to `.running` state |
| `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift` | Modify | Add `@Environment(\.syncCoordinator)`, pass `isSyncing` |
| `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Toolbar.swift` | Modify | Add `isSyncing: Bool` prop + `.symbolEffect(.rotate, isActive:)` |

---

## Task 1: Add `SyncCoordinatorKey` to AppEnvironment

**Files:**
- Modify: `ios/BooksBrowser/Services/AppEnvironment.swift`

- [ ] **Step 1: Add EnvironmentKey struct**

In `AppEnvironment.swift`, insert after `ICloudDownloadManagerKey` closing `}` (before `extension EnvironmentValues`):

```swift
private struct SyncCoordinatorKey: EnvironmentKey {
    static let defaultValue: SyncCoordinator = MainActor.assumeIsolated {
        SyncCoordinator()
    }
}
```

- [ ] **Step 2: Add `syncCoordinator` accessor inside the existing `extension EnvironmentValues` block**

The file already has `extension EnvironmentValues { ... }` containing all other keys. Add `syncCoordinator` **inside** that existing block (do not create a new extension):

```swift
var syncCoordinator: SyncCoordinator {
    get { self[SyncCoordinatorKey.self] }
    set { self[SyncCoordinatorKey.self] = newValue }
}
```

- [ ] **Step 3: Build to verify**

```bash
cd /Users/chenliangyu/MPSO/projects/kg
./ops/ios_build.sh
```

Expected: exit 0, no errors.

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/AppEnvironment.swift
git commit -m "ios: add SyncCoordinatorKey to AppEnvironment"
```

---

## Task 2: Inject `syncCoordinator` in BooksBrowserApp

**Files:**
- Modify: `ios/BooksBrowser/BooksBrowserApp.swift`

- [ ] **Step 1: Add property**

Add alongside the other `let` service properties (e.g. after `let networkMonitor`):

```swift
let syncCoordinator = SyncCoordinator()
```

- [ ] **Step 2: Inject into environment**

In `body`, add to the `.environment(...)` chain (e.g. after `.environment(\.iCloudDownloadManager, iCloudDownloadManager)`):

```swift
.environment(\.syncCoordinator, syncCoordinator)
```

- [ ] **Step 3: Build to verify**

```bash
./ops/ios_build.sh
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/BooksBrowserApp.swift
git commit -m "ios: inject app-level SyncCoordinator into environment"
```

---

## Task 3: Migrate SyncView from `@State` to `@Environment`

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/SyncView.swift`

- [ ] **Step 1: Replace `@State coordinator` with `@Environment`**

Remove:
```swift
@State private var coordinator = SyncCoordinator()
```

Add:
```swift
@Environment(\.syncCoordinator) private var coordinator
```

- [ ] **Step 2: Fix `.task` to not reset a running sync on re-open**

In `body`, change:
```swift
.task {
    refreshStepLayout()
}
```
to:
```swift
.task {
    refreshStepLayoutIfIdle()
}
```

`refreshStepLayoutIfIdle()` has `guard coordinator.phase != .running` — this prevents re-opening the sheet from calling `resetForRetry()` which would clear `steps` and freeze the UI while the background task still runs.

- [ ] **Step 3: Build to verify**

```bash
./ops/ios_build.sh
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/SyncView.swift
git commit -m "ios: migrate SyncView coordinator from @State to @Environment"
```

---

## Task 4: Show "關閉" button at all phases

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter.swift`

- [ ] **Step 1: Remove phase guard from toolbar close button**

Locate the toolbar item (in `body`):

```swift
.toolbar {
    ToolbarItem(placement: .topBarTrailing) {
        if state.phase == .ready || state.phase == .completed || state.phase == .failed {
            Button("關閉".localized) { dismiss() }
        }
    }
}
```

Replace with:

```swift
.toolbar {
    ToolbarItem(placement: .topBarTrailing) {
        Button("關閉".localized) { dismiss() }
    }
}
```

The "取消" button in the action area remains the only way to stop sync. Closing just dismisses the sheet; the coordinator continues running.

- [ ] **Step 2: Build to verify**

```bash
./ops/ios_build.sh
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter.swift
git commit -m "ios: show 關閉 button at all sync phases"
```

---

## Task 5: Add background-continue messaging to running header

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter+Header.swift`

- [ ] **Step 1: Add description to `.running` hero**

Locate the `.running` case in `headerView`:

```swift
case .running:
    VocabStatusHero(
        systemImage: "arrow.triangle.2.circlepath",
        tone: vocabSkin.palette.accent,
        title: "同步中…".localized
    ) {
        ProgressView()
            .controlSize(.large)
    }
    .transition(.blurReplace)
```

Add `description:` parameter:

```swift
case .running:
    VocabStatusHero(
        systemImage: "arrow.triangle.2.circlepath",
        tone: vocabSkin.palette.accent,
        title: "同步中…".localized,
        description: "離開後同步將繼續在背景執行，可隨時返回查看進度".localized
    ) {
        ProgressView()
            .controlSize(.large)
    }
    .transition(.blurReplace)
```

- [ ] **Step 2: Build to verify**

```bash
./ops/ios_build.sh
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter+Header.swift
git commit -m "ios: add background-continue message to sync running header"
```

---

## Task 6: Toolbar spinning indicator

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Toolbar.swift`

These two files must be changed atomically — adding the `isSyncing` prop to the toolbar modifier breaks the call site until both changes are saved. Build only after both steps are done.

- [ ] **Step 1: Add `isSyncing` prop to `VocabularyListToolbar`**

In `VocabularyListView+Toolbar.swift`, add to `VocabularyListToolbar`'s property list (after `let isLoggedIn`):

```swift
let isSyncing: Bool
```

Then replace the sync button body:

```swift
Button(action: onSync) {
    VocabToolbarGlyph(
        systemImage: "arrow.triangle.2.circlepath",
        badge: pendingCount > 0 ? "\(pendingCount)" : nil
    )
}
.accessibilityLabel("同步詞彙".localized)
```

With:

```swift
Button(action: onSync) {
    VocabToolbarGlyph(
        systemImage: "arrow.triangle.2.circlepath",
        badge: pendingCount > 0 ? "\(pendingCount)" : nil
    )
    .symbolEffect(.rotate, options: .repeating, isActive: isSyncing)
}
.accessibilityLabel("同步詞彙".localized)
```

Note: Button remains enabled while syncing — the user taps it to reopen the sheet and view live progress.

- [ ] **Step 2: Add `@Environment` and pass `isSyncing` in VocabularyListView**

In `VocabularyListView.swift`, add alongside other `@Environment` declarations:

```swift
@Environment(\.syncCoordinator) private var syncCoordinator
```

In `body`, update the `.modifier(VocabularyListToolbar(...))` call to include:

```swift
isSyncing: syncCoordinator.phase == .running,
```

- [ ] **Step 3: Build to verify**

```bash
./ops/ios_build.sh
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift \
        ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Toolbar.swift
git commit -m "ios: spinning toolbar indicator when sync is running"
```

---

## Final Verification

- [ ] **Manual smoke test checklist**
  1. Open sync sheet → tap "開始同步" → swipe sheet down → confirm toolbar icon is spinning
  2. Navigate away from vocab list → navigate back → toolbar still spinning
  3. Tap spinning toolbar icon → sheet reopens showing running state with "離開後同步將繼續在背景執行" and "關閉" button visible
  4. Close sheet again → sync continues, toolbar still spinning
  5. Re-open sheet after sync completes → shows completed state (not reset to ready)
  6. Tap "取消" in sheet → sync stops, toolbar icon returns to normal

- [ ] **Final build**

```bash
./ops/ios_build.sh
```

Expected: exit 0.
