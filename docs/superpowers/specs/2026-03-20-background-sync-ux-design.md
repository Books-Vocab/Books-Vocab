# Background Sync UX Design

**Date:** 2026-03-20
**Scope:** iOS — `SyncCoordinator` lifetime promotion + background indicator
**Deployment Target:** iOS 26+

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

`SyncCoordinator` is promoted to app-level, created once in `BooksBrowserApp` alongside `kgService` and `authManager`. It is injected via a new `EnvironmentKey` following the pattern of `ICloudDownloadManagerKey` in `AppEnvironment.swift` (concrete class, no `nonisolated(unsafe)` needed).

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

Added to `Services/AppEnvironment.swift` (follows `ICloudDownloadManagerKey` pattern — concrete class, `MainActor.assumeIsolated`, no protocol):

```swift
private struct SyncCoordinatorKey: EnvironmentKey {
    static let defaultValue: SyncCoordinator = MainActor.assumeIsolated {
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

**Design note:** Uses concrete `SyncCoordinator` (not `any SyncCoordinating` protocol) because the coordinator is not mocked in tests and is always the same class. Aligns with `ICloudDownloadManagerKey`. If mock support is needed later, introduce a protocol at that point (YAGNI).

---

## Sheet Close Behavior

**Before:** Toolbar "關閉" button hidden during `.running`. User trapped in sheet.

**After:**
- "關閉" button visible at **all phases** (remove `phase == .ready || .completed || .failed` guard from `SyncPresenter.swift`)
- No `interactiveDismissDisabled` — coordinator persists through dismissal naturally
- Running header (`SyncPresenter+Header.swift`) adds a description line:
  `"離開後同步將繼續在背景執行，可隨時返回查看進度"`
- "取消" button remains the only way to stop sync
- `SyncPresenter+ActionArea.swift` — `dismiss()` in `.completed` case is correct as-is (closes sheet, does not affect coordinator)

### Sheet Re-open While Sync Running

When the user re-opens the sheet during an active sync, `SyncView` body is re-evaluated and `.task` fires again. The current code calls `refreshStepLayout()` unconditionally, which would call `resetForRetry()` → `phase = .ready` and clear `steps`, breaking the live UI.

**Fix:** Change `SyncView`'s `.task` block from `refreshStepLayout()` to `refreshStepLayoutIfIdle()`, which already has `guard coordinator.phase != .running`.

---

## Toolbar Indicator

`VocabularyListToolbar` receives a new `isSyncing: Bool` prop.

When `isSyncing == true`, the sync button icon uses `.symbolEffect(.rotate, options: .repeating)` on `arrow.triangle.2.circlepath` (iOS 17+ API, well within iOS 26 target).

`VocabularyListView` changes:
1. Add `@Environment(\.syncCoordinator) private var syncCoordinator`
2. Pass `isSyncing: syncCoordinator.phase == .running` into `VocabularyListToolbar`

---

## Files Changed

| File | Change |
|------|--------|
| `Services/AppEnvironment.swift` | Add `SyncCoordinatorKey` + `\.syncCoordinator` |
| `BooksBrowserApp.swift` | Add `let syncCoordinator = SyncCoordinator()`, inject via `.environment` |
| `Views/Vocabulary/SyncView.swift` | `@State coordinator` → `@Environment(\.syncCoordinator)`; `.task` → `refreshStepLayoutIfIdle()` |
| `Views/Vocabulary/Scenes/SyncPresenter.swift` | Remove phase guard on "關閉" toolbar button |
| `Views/Vocabulary/Scenes/SyncPresenter+Header.swift` | Add description to `.running` state |
| `Views/Vocabulary/VocabularyListView.swift` | Add `@Environment(\.syncCoordinator)`, pass `isSyncing` to toolbar |
| `Views/Vocabulary/VocabularyListView+Toolbar.swift` | Add `isSyncing` prop + `.symbolEffect(.rotate, options: .repeating)` |
| `Views/Vocabulary/Scenes/SyncPresenter+ActionArea.swift` | No change — `dismiss()` in `.completed` is correct |

---

## Out of Scope

- App-backgrounding persistence (requires `BGProcessingTask` — separate feature)
- Global app-wide indicator (only vocab list toolbar)
- Sync auto-start on app launch
- Mock/protocol support for `SyncCoordinator` in tests (YAGNI)
