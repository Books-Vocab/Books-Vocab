# Toast/Banner 通知覆蓋增強 Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 讓每個 sheet 自動支援 toast overlay，並為所有使用者主動操作補上成功/失敗通知。
**Architecture:** 新增 `toastSheet`/`toastFullScreenCover` wrapper 取代原生 `.sheet()`，加上 `safeSaveWithToast()` helper 統一本地儲存失敗通知。
**Tech Stack:** SwiftUI ViewModifier, SwiftData ModelContext extension

---

## Task 1: 基礎設施 — `View+ToastSheet.swift` + `safeSaveWithToast()`

**Files:**
- Create: `ios/BooksBrowser/UIComponents/View+ToastSheet.swift`
- Modify: `ios/BooksBrowser/Services/ModelContext+SafeSave.swift`

- [ ] **Step 1: 建立 `View+ToastSheet.swift`**

```swift
import SwiftUI

extension View {
    func toastSheet<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        sheet(isPresented: isPresented, onDismiss: onDismiss) {
            content().toastOverlay()
        }
    }

    func toastSheet<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        sheet(item: item, onDismiss: onDismiss) { value in
            content(value).toastOverlay()
        }
    }

    func toastFullScreenCover<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        fullScreenCover(isPresented: isPresented, onDismiss: onDismiss) {
            content().toastOverlay()
        }
    }

    func toastFullScreenCover<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        fullScreenCover(item: item, onDismiss: onDismiss) { value in
            content(value).toastOverlay()
        }
    }
}
```

- [ ] **Step 2: 在 `ModelContext+SafeSave.swift` 加入 `safeSaveWithToast()`**

在現有 `safeSave()` 方法下方加入：

```swift
@discardableResult
func safeSaveWithToast(
    _ toastCoordinator: AppToastCoordinator,
    file: String = #file, line: Int = #line
) -> Bool {
    let ok = safeSave(file: file, line: line)
    if !ok { toastCoordinator.error("儲存失敗") }
    return ok
}
```

- [ ] **Step 3: iOS build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**
`ios: add toastSheet wrapper and safeSaveWithToast helper`

---

## Task 2: 全專案 sheet 遷移（26 sheet + 2 fullScreenCover）

**Files:**
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/SyncView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/KnowledgeGraphView.swift`
- Modify: `ios/BooksBrowser/Views/Reader/ReaderView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Overlay/LinkedCardOverlayStack.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookFilterChip.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/ArchivedVocabSheet.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift`

- [ ] **Step 1: 全部 `.sheet(` → `.toastSheet(`**

在每個檔案中，將 `.sheet(isPresented:` 或 `.sheet(item:` 替換為 `.toastSheet(isPresented:` 或 `.toastSheet(item:`。

完整清單（26 處）：
1. `BookshelfView.swift` — `.sheet(isPresented: $coordinator.showSettings)`
2. `SyncView.swift` — `.sheet(isPresented: $showSettings)`
3. `KnowledgeGraphView.swift` — `.sheet(item: $coordinator.selectedEntry)`
4. `ReaderView.swift` — 4 處 `.sheet(`（TOC、Paywall、WordDetail、NotebookPicker）
5. `LinkedCardOverlayStack.swift` — `.sheet(item: $editingEntry)`
6. `StatsPresenter.swift` — `.sheet(isPresented: $showCalendar)`
7. `NotebookListView.swift` — 3 處 `.sheet(`（create、edit、archive）
8. `NotebookFilterChip.swift` — `.sheet(isPresented: $showPicker)`
9. `TodayReviewView.swift` — `.sheet(item: $state.tappedLink)`
10. `KGVocabView.swift` — 2 處 `.sheet(`（selectedEntry、notebookPicker）
11. `WordDetailSheet.swift` — 2 處 `.sheet(`（editing、addLink）
12. `SettingsView.swift` — 2 處 `.sheet(`（integrationInfo、paywall）
13. `ArchivedVocabSheet.swift` — `.sheet(item: $selectedEntry)`
14. `VocabularyListView+Sheets.swift` — 5 處（syncView、settings、shareSheet、wordDetail、iPad TodayReview）

- [ ] **Step 2: 全部 `.fullScreenCover(` → `.toastFullScreenCover(`**

2 處：
1. `NotebookListView.swift` — `.fullScreenCover(item: $activeReviewSession)`
2. `VocabularyListView+Sheets.swift` — `.fullScreenCover(item: ...coordinator.activeReviewSession...)`

- [ ] **Step 3: 移除手動 `.toastOverlay()`**

2 處：
- `WordDetailSheet.swift:80` — 移除 `.toastOverlay()`
- `TodayReviewView.swift:86` — 移除 `.toastOverlay()`

保留 `BooksBrowserApp.swift:161` 的 root `.toastOverlay()`。

- [ ] **Step 4: iOS build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**
`ios: migrate all sheets to toastSheet/toastFullScreenCover`

---

## Task 3: Coordinator toast 注入 + HIGH 級通知補齊

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListCoordinator.swift`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsCoordinator.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabCoordinator.swift`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfCoordinator.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListCoordinator.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/ArchivedVocabSheet.swift`
- Modify: `ios/BooksBrowser/Views/Reader/ReaderVocabularyContext.swift`
- Modify: 呼叫端 View 檔案（傳入 toastCoordinator）

- [ ] **Step 1: `NotebookListCoordinator` — createNotebook / updateNotebook 加 toast**

在 `createNotebook` 方法簽名加 `toastCoordinator: AppToastCoordinator` 參數：
- 成功路徑加 `toastCoordinator.success("已建立")`
- catch block 加 `toastCoordinator.error("建立失敗")`
- `safeSave()` → `safeSaveWithToast(toastCoordinator)`

同理 `updateNotebook`：
- 成功加 `toastCoordinator.success("已更新")`
- catch 加 `toastCoordinator.error("更新失敗")`
- `safeSave()` → `safeSaveWithToast(toastCoordinator)`

其他已有 toast 的方法（`deleteNotebook`）的 `safeSave()` → `safeSaveWithToast(toastCoordinator)`。
`moveEntries` 相關方法的 `safeSave()` → `safeSaveWithToast(toastCoordinator)`（需加參數）。

- [ ] **Step 2: `SettingsCoordinator` — 加 toast 參數**

`scheduleOptionalIntegrationSave` 方法加 `toastCoordinator` 參數：
- catch block 加 `toastCoordinator.error("儲存失敗")`

`updateTranslationLanguage` 方法加 `toastCoordinator` 參數：
- catch block 加 `toastCoordinator.error("設定儲存失敗")`

更新呼叫端 `SettingsView.swift` 傳入 `toastCoordinator`。

- [ ] **Step 3: `KGVocabCoordinator` — 全方法加 toast**

以下方法加 `toastCoordinator` 參數，`safeSave()` → `safeSaveWithToast(toastCoordinator)`：
- `handleDeleteTap` — 成功加 `toast.success("已刪除")`
- `handleBatchDelete` — 成功加 `toast.success("已刪除 \(count) 個")`
- `handleBatchArchive` — 成功加 `toast.success("已封存 \(count) 個")`
- `handleBatchMove` — 成功加 `toast.success("已移動 \(count) 個")`

更新 protocol `KGVocabCoordinating` 及呼叫端 View 傳入 `toastCoordinator`。

- [ ] **Step 4: `BookshelfCoordinator` — deleteBook 加 toast**

`deleteBook` 方法加 `toastCoordinator` 參數：
- 成功加 `toast.success("已刪除")`
- `safeSave()` → `safeSaveWithToast(toastCoordinator)`

更新 `BookshelfView.swift` 呼叫端。

- [ ] **Step 5: `VocabularyListCoordinator` — handlePendingRemoval 加 toast + export 失敗處理**

`handlePendingRemoval`（private，經由 `handlePendingActionTap` 呼叫）：
- `safeSave()` → `safeSaveWithToast(toastCoordinator)`
- `handlePendingActionTap` 方法簽名加 `toastCoordinator` 參數並向下傳遞

`exportCSV` / `exportJSON` / `exportAnki`：
- 這三個方法呼叫 `VocabularyExporter` 的靜態方法取得 URL
- 若回傳 `nil`（寫入失敗），加 `toastCoordinator.error("匯出失敗")`
- 方法簽名加 `toastCoordinator` 參數

更新呼叫端 View。

- [ ] **Step 6: `ArchivedVocabSheet` — unarchive 加 toast**

`safeSave()` → `safeSaveWithToast(toastCoordinator)`
成功路徑加 `toastCoordinator.success("已取消封存")`

- [ ] **Step 7: `ReaderVocabularyContext` — save/delete 加 toast**

Line 34（save word）和 line 48（delete word）的 `safeSave()` → `safeSaveWithToast(toastCoordinator)`。
Line 75（背景 context save）保持 `safeSave()`。

需加 `toastCoordinator` 參數或屬性。

- [ ] **Step 8: iOS build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 9: Commit**
`ios: add toast notifications for user-initiated operations`

---

## Task 4: MEDIUM 級通知 + 最終驗證

**Files:**
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`（匯入成功 toast）
- Modify: `ios/BooksBrowser/Services/ICloudDownloadManager.swift`（下載失敗 toast）

- [ ] **Step 1: BookshelfView — EPUB 匯入成功 toast**

在匯入完成的成功路徑加 `toastCoordinator.success("已匯入")`。

- [ ] **Step 2: ICloudDownloadManager — 下載失敗 toast**

在 download trigger 的 catch block 加 `toastCoordinator.warning("iCloud 下載失敗")`。
需評估是否能存取 toastCoordinator（可能需在呼叫端處理）。

- [ ] **Step 3: iOS build 最終驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**
`ios: add medium-priority toast notifications`
