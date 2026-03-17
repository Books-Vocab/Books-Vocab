# 書本綁定單字本 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每本書記住上次使用的單字本，閱讀時自動存入正確的 notebook，解決「忘記切換」的靜默出錯問題。

**Architecture:** 在 `Book` model 加 `preferredNotebookId: String?`。存字時優先序為 `book.preferredNotebookId → UserDefaults["activeNotebookId"] → "default"`。同步時按 `notebookId` 分組上傳。閱讀器內顯示目標單字本名稱，可點擊切換。

**Tech Stack:** SwiftData（輕量遷移）、SwiftUI

---

## File Map

| 動作 | 檔案 | 職責 |
|------|------|------|
| Modify | `ios/BooksBrowser/Models/Book.swift` | 加 `preferredNotebookId: String?` |
| Modify | `ios/BooksBrowser/Views/Reader/ReaderVocabularyContext.swift` | `saveEntry()` 帶入 resolved notebookId |
| Modify | `ios/BooksBrowser/Views/Reader/ReaderView+Panels.swift` | 傳 resolved notebookId 到 context |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncCoordinator.swift` | batchAdd/triggerPipeline 按 notebookId 分組 |
| Modify | `ios/BooksBrowser/Services/KGService+Sync.swift` | backgroundSync 改用多本 pull |
| Modify | `ios/BooksBrowser/Services/BackgroundSyncActor.swift` | 加 `distinctNotebookIds()` helper |
| Create | `ios/BooksBrowser/Views/Reader/ReaderNotebookPicker.swift` | 閱讀器內的單字本選擇 UI |
| Modify | `ios/BooksBrowser/Views/Reader/ReaderView.swift` | 整合 notebook picker |

---

### Task 1: Book Model — 加 preferredNotebookId

**Files:**
- Modify: `ios/BooksBrowser/Models/Book.swift:14-40`

- [ ] **Step 1: 加欄位**

在 `Book` class 中加入：

```swift
var preferredNotebookId: String?   // 綁定的單字本 remoteId（nil = 跟隨全域設定）
```

位置：在 `progression` 之後、`init` 之前。

`init` 不需改動 — SwiftData optional 屬性預設為 nil，輕量遷移自動處理。

- [ ] **Step 2: 加 resolved helper**

在 `Book` class 底部加入：

```swift
/// 此書的目標單字本 ID（優先序：書本綁定 → 全域使用中 → 預設）
///
/// 注意：不在此處驗證 notebook 是否已刪除，因為 @Model computed property
/// 無法存取 ModelContext。已刪除 notebook 的防護由 ReaderNotebookPicker
/// 在 UI 層處理（選擇時過濾 isDeleted，若綁定的本被刪則自動清除綁定）。
var resolvedNotebookId: String {
    if let bound = preferredNotebookId { return bound }
    return UserDefaults.standard.string(forKey: "activeNotebookId") ?? "default"
}
```

- [ ] **Step 3: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Models/Book.swift
git commit -m "ios: Book model 加 preferredNotebookId 綁定欄位"
```

---

### Task 2: ReaderVocabularyContext — 存字帶入 notebookId

**Files:**
- Modify: `ios/BooksBrowser/Views/Reader/ReaderVocabularyContext.swift:7-58`
- Modify: `ios/BooksBrowser/Views/Reader/ReaderView+Panels.swift:5-12`

- [ ] **Step 1: context 加 notebookId 屬性**

修改 `ReaderVocabularyContext`，在 `currentLocator` 之後加：

```swift
let notebookId: String
```

- [ ] **Step 2: saveEntry() 設定 notebookId**

在 `saveEntry()` 中，`entry.bookId = book.id` 之後加一行：

```swift
entry.notebookId = notebookId
```

- [ ] **Step 3: 更新 ReaderView+Panels 的 context 建構**

修改 `ReaderView+Panels.swift` 中的 `vocabularyContext` computed property：

```swift
var vocabularyContext: ReaderVocabularyContext {
    ReaderVocabularyContext(
        vocabulary: allVocabulary,
        modelContext: modelContext,
        book: book,
        currentLocator: currentLocator,
        notebookId: book.resolvedNotebookId
    )
}
```

- [ ] **Step 4: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/Views/Reader/ReaderVocabularyContext.swift
git add ios/BooksBrowser/Views/Reader/ReaderView+Panels.swift
git commit -m "ios: saveEntry() 從 book 綁定帶入 notebookId"
```

---

### Task 3: SyncCoordinator — 按 notebookId 分組上傳

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncCoordinator.swift:136-178`

- [ ] **Step 1: batchAdd 改為分組上傳**

將 `SyncCoordinator.startSync()` 中 batchAdd 的區塊（約 L136-169）改為：

```swift
if !adds.isEmpty {
    updateStep("upload_add", status: .running, total: adds.count)

    let grouped = Dictionary(grouping: adds, by: \.notebookId)
    var totalCreated = 0
    var totalSkipped = 0
    var batchFailed = false

    for (nbId, entries) in grouped {
        do {
            entries.forEach { $0.prepareForRetryAttempt() }
            let response = try await kgService.batchAdd(entries: entries, notebookId: nbId)

            for entry in entries {
                if let cardId = response.cardIds[entry.word] {
                    entry.kgCardId = cardId
                }
            }
            totalCreated += response.created
            totalSkipped += response.skipped
        } catch {
            entries.forEach { $0.markSyncFailed() }
            encounteredFailure = true
            batchFailed = true
        }
    }
    modelContext.safeSave()

    if batchFailed {
        let failedCount = adds.filter(\.isFailed).count
        updateStep(
            "upload_add",
            status: .error,
            current: adds.count - failedCount,
            total: adds.count,
            detail: L10n.format("部分上傳失敗（%@ 筆）", "\(failedCount)")
        )
    } else {
        updateStep(
            "upload_add",
            status: .done,
            current: adds.count,
            total: adds.count,
            detail: L10n.format("%@ 新增, %@ 已存在", "\(totalCreated)", "\(totalSkipped)")
        )
    }
}
```

- [ ] **Step 2: triggerPipeline 改為多本觸發**

將 triggerPipeline 區塊（約 L171-178）改為：

```swift
updateStep("trigger", status: .running)
do {
    let uploadedNotebooks = Set(adds.map(\.notebookId))
    let notebooksToTrigger = uploadedNotebooks.isEmpty ? ["default"] : Array(uploadedNotebooks)
    for nbId in notebooksToTrigger {
        try await kgService.triggerPipeline(notebookId: nbId)
    }
    updateStep("trigger", status: .done, detail: L10n.string("已交由伺服器背景處理"))
} catch {
    encounteredFailure = true
    updateStep("trigger", status: .error, detail: L10n.format("無法觸發: %@", error.localizedDescription))
}
```

- [ ] **Step 3: pull 改為多本拉取**

將 pull 區塊（約 L191-205）改為：

```swift
updateStep("pull", status: .running, detail: L10n.string("從遠端下載知識庫..."))

// 收集所有本地有資料的 notebook（用 distinctNotebookIds 確保涵蓋所有本）
let syncActor = BackgroundSyncActor(modelContainer: modelContext.container)
let distinctIds = (try? await syncActor.distinctNotebookIds()) ?? []
let allLocalNotebooks = distinctIds.isEmpty ? ["default"] : distinctIds

var pipelinePending = false
for nbId in allLocalNotebooks {
    let pending = try await kgService.pullCardsToLocal(container: modelContext.container, progress: { [weak self] detail, current, total in
        Task { @MainActor in
            self?.updateStep("pull", status: .running, current: current, total: total, detail: detail)
        }
    }, notebookId: nbId)
    if pending { pipelinePending = true }
}

var retryCount = 0
while pipelinePending && retryCount < 3 {
    retryCount += 1
    updateStep("pull", status: .running, detail: L10n.format("等待 AI 處理完成（%@/3）...", "\(retryCount)"))
    try await Task.sleep(for: .seconds(10))
    if Task.isCancelled { break }
    pipelinePending = false
    for nbId in allLocalNotebooks {
        let pending = try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil, notebookId: nbId)
        if pending { pipelinePending = true }
    }
}

// Also pull daily stats from server
try? await kgService.pullDailyStats(container: modelContext.container)
```

- [ ] **Step 4: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/SyncCoordinator.swift
git commit -m "ios: SyncCoordinator 按 notebookId 分組上傳與拉取"
```

---

### Task 4: backgroundSync — 多本支援

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+Sync.swift:146-186`

- [ ] **Step 1: backgroundSync pull 改多本**

修改 `backgroundSync()` 中的 pull 區塊。需要先取得所有本地 notebook ID，改為逐本 pull：

```swift
// 取得所有本地存在的 notebookId（從 VocabularyEntry）
let actor = BackgroundSyncActor(modelContainer: container)
let localNotebookIds = try? await actor.distinctNotebookIds()
let notebooksToPull = (localNotebookIds ?? []).isEmpty ? ["default"] : (localNotebookIds ?? [])

do {
    for nbId in notebooksToPull {
        try await pullCardsToLocal(container: container, progress: nil, notebookId: nbId)
    }
} catch {
    AppLog.kg.warning("backgroundSync pull failed: \(error.localizedDescription)")
    failures.append("pull")
}
```

- [ ] **Step 2: BackgroundSyncActor 加 distinctNotebookIds()**

在 `BackgroundSyncActor` 中加入：

```swift
func distinctNotebookIds() throws -> [String] {
    let descriptor = FetchDescriptor<VocabularyEntry>()
    let entries = try modelContext.fetch(descriptor)
    return Array(Set(entries.map(\.notebookId)))
}
```

（檔案：`ios/BooksBrowser/Services/BackgroundSyncActor.swift`）

- [ ] **Step 3: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+Sync.swift
git add ios/BooksBrowser/Services/BackgroundSyncActor.swift
git commit -m "ios: backgroundSync 支援多本 pull"
```

---

### Task 5: 閱讀器 Notebook Picker UI

**Files:**
- Create: `ios/BooksBrowser/Views/Reader/ReaderNotebookPicker.swift`
- Modify: `ios/BooksBrowser/Views/Reader/ReaderView.swift`（整合 picker 觸發）

**前置讀取（動手前必做）：**
1. 讀 `docs/references/ui_component_pattern_inventory.md`
2. 讀 `docs/references/ui_review_checklist.md`
3. 讀 `ios/BooksBrowser/Models/AppMetrics.swift`（AppTheme / AppMotion token）

- [ ] **Step 1: 建立 ReaderNotebookPicker**

建立 `ios/BooksBrowser/Views/Reader/ReaderNotebookPicker.swift`：

此元件是一個 sheet，顯示所有 notebook 讓用戶為當前書選擇目標單字本。

核心邏輯：
- 用 `@Query` 取 `Notebook` 列表（排除 `isDeleted`）
- 選中後設定 `book.preferredNotebookId = notebook.remoteId`
- 顯示當前選中狀態（checkmark）
- 提供「跟隨全域設定」選項（設為 nil）
- **已刪除 notebook 防護**：`onAppear` 時檢查 `book.preferredNotebookId` 是否指向已刪除/不存在的 notebook，若是則自動清除綁定（設為 nil）

所有色彩、字型、間距必須走 design system token（`AppTheme`、`AppFonts`、`AppMetrics`）。

- [ ] **Step 2: 在閱讀器中加入觸發入口**

在 `ReaderView.swift` 中加入：
- 一個 `@State private var showNotebookPicker = false` 狀態
- 在 toolbar 或翻譯面板中加入一個顯示當前目標單字本名稱的按鈕
- 按鈕點擊觸發 `.sheet(isPresented: $showNotebookPicker)`

需先讀取 `ReaderView.swift` 確認現有 toolbar 結構，找到適合放置的位置。

- [ ] **Step 3: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: UI 自查**

對照 `docs/references/ui_review_checklist.md` 五大項逐一確認：
- 無 raw color / raw font / raw spacing
- 動畫走 AppMotion token
- Theme 從 `@Environment(\.appTheme)` 注入

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/Views/Reader/ReaderNotebookPicker.swift
git add ios/BooksBrowser/Views/Reader/ReaderView.swift
git commit -m "ios: 閱讀器內 Notebook Picker — 書本綁定單字本 UI"
```

---

### Task 6: 最終整合與 PR

- [ ] **Step 1: 全量編譯**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 2: 建立 PR**

```bash
git push -u origin HEAD
gh pr create --title "ios: 書本綁定單字本 — 閱讀時自動存入正確 notebook" --body "..."
```
