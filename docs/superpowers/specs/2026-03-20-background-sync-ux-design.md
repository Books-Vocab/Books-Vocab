# Background Sync UX Design

**Date:** 2026-03-20
**Scope:** iOS — `SyncCoordinator` lifetime promotion + background indicator

---

## Problem

`SyncCoordinator` currently lives as `@State` inside `SyncView` (a `.sheet`). When the user dismisses the sheet — including interactive swipe-down — the coordinator is deallocated and `pipelineTask` is cancelled. Sync cannot continue in the background.

Additionally, the toolbar "close" button is hidden during `.running`, forcing users to stay in the sheet until sync completes.

---

## Goal

- Sync continues as long as the user has not tapped "取消", regardless of whether the sheet is open
- User can close the sheet, navigate elsewhere, and return to see live progress
- Toolbar sync button shows a spinning indicator while sync is running
- Sheet clearly communicates "you can leave — sync continues"

---

## Architecture

### SyncCoordinator Lifetime

`SyncCoordinator` is promoted to app-level, created once in `BooksBrowserApp` alongside `kgService` and `authManager`. It is injected via a new `EnvironmentKey` following the exact pattern of `KGServiceEnvironmentKey` in `AppEnvironment.swift`.

```
BooksBrowserApp
  └─ let syncCoordinator = SyncCoordinator()   // @MainActor, lives forever
       .environment(\.syncCoordinator, syncCoordinator)

SyncView
  └─ @Environment(\.syncCoordinator) private var coordinator  // reads, no longer owns

VocabularyListView
  └─ @Environment(\.syncCoordinator) private var syncCoordinator  // for toolbar indicator
```

### EnvironmentKey

Added to `Services/AppEnvironment.swift`:

```swift
private struct SyncCoordinatorKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: SyncCoordinator = MainActor.assumeIsolated {
        SyncCoordinator()
    }
}

extension EnvironmentValues {
    var syncCoordinator: SyncCoordinator {
        get { self[SyncCoordinatorKey.self] }
        set { self[SyncCoordinatorKey.self] = newValue }
    }
}
```

---

## Sheet Close Behavior

**Before:** Toolbar "關閉" button hidden during `.running`. User trapped in sheet.

**After:**
- "關閉" button visible at **all phases** (remove `phase == .ready || .completed || .failed` guard)
- No `interactiveDismissDisabled` — coordinator persists through dismissal naturally
- Running header (`SyncPresenter+Header.swift`) adds a description line:
  `"離開後同步將繼續在背景執行，可隨時返回查看進度"`
- "取消" button remains the only way to stop sync

---

## Toolbar Indicator

`VocabularyListToolbar` receives a new `isSyncing: Bool` prop.

When `isSyncing == true`, the sync button icon uses `.symbolEffect(.rotate, options: .repeating)` on the `arrow.triangle.2.circlepath` symbol (SF Symbols rotate effect — consistent with existing `AppMotion` usage).

`VocabularyListView` computes:
```swift
isSyncing: syncCoordinator.phase == .running
```

---

## Files Changed

| File | Change |
|------|--------|
| `Services/AppEnvironment.swift` | Add `SyncCoordinatorKey` + `\.syncCoordinator` |
| `BooksBrowserApp.swift` | Add `let syncCoordinator = SyncCoordinator()`, inject via `.environment` |
| `Views/Vocabulary/SyncView.swift` | `@State coordinator` → `@Environment(\.syncCoordinator)` |
| `Views/Vocabulary/Scenes/SyncPresenter.swift` | Remove phase guard on "關閉" toolbar button |
| `Views/Vocabulary/Scenes/SyncPresenter+Header.swift` | Add description to `.running` state |
| `Views/Vocabulary/VocabularyListView.swift` | Read `syncCoordinator`, pass `isSyncing` to toolbar |
| `Views/Vocabulary/VocabularyListView+Toolbar.swift` | Add `isSyncing` prop + `.symbolEffect(.rotate)` |

---

## Out of Scope

- App-backgrounding persistence (requires `BGProcessingTask` — separate feature)
- Global app-wide indicator (only vocab list toolbar)
- Sync auto-start on app launch
