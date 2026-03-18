# 單字列表選取模式設計

## 概述

將知識庫單字列表的三種操作（移動、封存、刪除）整合為統一的選取模式，取代現有分散的左滑封存 + context menu 刪除。

## 現狀

| 操作 | 入口 | 方式 |
|------|------|------|
| 封存 | `VocabSwipeRow` 左滑 | 即時呼叫 `archiveCard()` API |
| 刪除 | 長按 context menu | `queueDelete()` → 待收錄 tab 緩衝 → 同步時送出 |
| 移動 | 不存在 | — |

## 設計

### 進入選取模式

- **觸發**：長按任一單字卡片
- 進入選取模式，該字自動勾選
- 列表每列左側出現圓形 checkbox
- 點選其他單字追加 / 取消勾選

### 退出選取模式

- 執行操作（移動 / 封存 / 刪除）後**自動退出**
- 導覽列顯示「取消」按鈕，供使用者改變主意時手動退出
- 切換 review state filter 時自動退出選取模式

### 全選

- 選取模式期間，導覽列顯示「全選 / 取消全選」按鈕
- 全選範圍 = 當前篩選後的可見列表

### 底部工具列

選取模式期間，底部浮現工具列，三個按鈕：

| 按鈕 | 圖示 | 條件 | 行為 |
|------|------|------|------|
| 移動 | `folder` | ≥ 1 選取 | 彈出 notebook 選擇 sheet → 選完呼叫 batch API → 退出 |
| 封存 | `archivebox` | ≥ 1 選取 | 逐一呼叫 `archiveCard()` API → 退出 |
| 刪除 | `trash` | ≥ 1 選取 | 逐一呼叫 `queueDelete()` → 退出 |

### 封存 partial failure 處理

封存逐一呼叫 API，若中途失敗：
- 已成功封存的卡片保持封存（不回滾）
- 顯示錯誤提示「N/M 張卡片已封存，部分失敗」
- 仍然退出選取模式

### 移除的舊操作

- **廢除** `VocabSwipeRow` 左滑封存按鈕
- **廢除** context menu 刪除選項
- `VocabSwipeRow` 元件可移除或簡化為純展示列

### 不變的部分

- 非選取模式時，點擊單字仍開啟 `WordDetailSheet`
- 刪除仍走 `queueDelete()` → 待收錄 tab 可復原 → 同步時真正刪除
- 封存仍走現有 `archiveCard()` API
- 封存列表（`ArchivedVocabSheet`）保持不變
- 知識庫列表已透過 `shouldAppearInKnowledgeList`（排除 `isArchived`）過濾，不會選到已封存卡片

## 後端變更

### 新增 API：批次移動

```
PATCH /api/vocab/move
Query: notebook_id (來源 notebook)
Body: { "words": ["apple", "book", ...], "to_notebook_id": "target-id" }
Response: { "moved": 2 }
```

邏輯：
1. 在來源 notebook 中查找指定 words 的非刪除卡片
2. 更新 `notebook_id` 為目標值，更新 `updated_at`
3. 單一 transaction，原子操作
4. Graph link 遷移：從來源 notebook 的 `GraphStore`（per-notebook JSON）中移除相關 link，在目標 notebook 的 `GraphStore` 中重建（或標記為 candidate 待 pipeline 重新生成）

### 不需要新增的 API

- 封存：沿用 `PATCH /api/vocab/{word}/archive`
- 刪除：iOS 端本地 queue，沿用同步流程

## iOS 變更

### 新增檔案

| 檔案 | 路徑 | 職責 |
|------|------|------|
| `SelectionModeState.swift` | `Views/Vocabulary/Scenes/` | 選取模式狀態管理 |
| `SelectionToolbar.swift` | `Views/Vocabulary/Components/` | 底部工具列 View |
| `NotebookPickerSheet.swift` | `Views/Vocabulary/Scenes/` | 移動目標 notebook 選擇 sheet |

### 修改檔案

| 檔案 | 路徑 | 變更 |
|------|------|------|
| `KGVocabPresenter.swift` | `Views/Vocabulary/Scenes/` | 移除 `VocabSwipeRow` 和 context menu；加入 checkbox + 長按手勢；接入選取狀態 |
| `KGVocabView.swift` | `Views/Vocabulary/Scenes/` | 整合 `SelectionModeState`；處理操作 callback（移動 / 封存 / 刪除）；封存邏輯從 View 搬到 Coordinator |
| `KGVocabCoordinator.swift` | `Views/Vocabulary/Scenes/` | 新增 `handleBatchMove`、`handleBatchArchive`、`handleBatchDelete` 方法 |
| `KGService+VocabCRUD.swift` | `Services/` | 新增 `moveCards(words:fromNotebook:toNotebook:)` |
| `VocabSwipeRow.swift` | `Views/Vocabulary/Components/` | 移除或簡化（不再需要 swipe action） |

所有路徑相對於 `ios/BooksBrowser/`。

### 選取模式狀態

```swift
@Observable
final class SelectionModeState {
    var isSelecting = false
    var selectedIDs: Set<UUID> = []

    func toggle(_ id: UUID) { ... }
    func selectAll(_ ids: [UUID]) { ... }
    func deselectAll() { ... }
    func exit() { isSelecting = false; selectedIDs.removeAll() }
}
```

### 操作流程

**ID → word 映射**：iOS 端以 `UUID` 追蹤選取，呼叫 API 前從 `syncedEntries` 中查找對應的 `word` 和 `notebookId`。

**移動：**
1. 點擊「移動」→ present `NotebookPickerSheet`（排除當前 notebook）
2. 選擇目標 notebook → 呼叫 `moveCards()` batch API
3. 成功後更新本地 `VocabularyEntry.notebookId`
4. 退出選取模式

**封存：**
1. 點擊「封存」→ 逐一呼叫 `archiveCard(archived: true)`
2. 成功的更新本地 `entry.isArchived = true`；失敗的跳過並累計錯誤
3. 全部完成後退出選取模式；若有失敗顯示提示

**刪除：**
1. 點擊「刪除」→ 逐一呼叫 `entry.queueDelete()`（純本地，無網路呼叫）
2. 卡片移至待收錄 tab（可復原）
3. 退出選取模式

## 不在範圍內

- 待收錄 tab 的選取模式（僅知識庫 tab）
- 封存列表的批次操作
- 跨 notebook 批次操作（一次只操作一個 notebook 內的卡片）
