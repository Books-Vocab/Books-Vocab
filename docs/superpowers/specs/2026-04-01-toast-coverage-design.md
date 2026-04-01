# Toast/Banner 通知覆蓋增強 — Design Spec

## Problem

iOS app 有兩套通知系統（AppToast、AppBanner），但覆蓋率極低：

- **13 次 toast 呼叫**，其中 10 次是「已複製」— 幾乎只服務複製操作
- **45 個檔案有 catch block**，大部分靜默吞錯誤無使用者回饋
- **28 個 sheet/fullScreenCover 中只有 2 個**掛載 `.toastOverlay()`，巢狀 sheet 的 toast 完全不可見
- 無統一規範決定何時用 toast vs banner vs alert

## Goals

1. 每個 sheet/fullScreenCover 自動具備 toast 渲染能力
2. 使用者主動操作的成功/失敗一律有回饋
3. 建立四級通知規範，新功能可直接遵循

## Non-Goals

- 不改 AppToast / AppBanner 的視覺設計
- 不為背景自癒操作加通知（review push、stats sync、cache）
- 不引入 notification queue — 多個 toast 同時觸發時只顯示最後一個，這是可接受的行為（`AppToastCoordinator.show()` 覆蓋前一個）

---

## Design

### A. 全域自動 Toast Overlay（基礎設施）

#### A1. `View+ToastSheet.swift` — Sheet wrapper with auto overlay

新增 4 個 View extension method，包裹 `.toastOverlay()`。

命名為 `toastSheet` / `toastFullScreenCover`，避免與現有 `.appSheet(_ preset: AppSheetPreset)`（管 presentation detent）衝突：

```swift
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

**巢狀 sheet 行為：** `toastCoordinator` 是單一 instance（從 root environment 繼承）。巢狀 sheet 的多層 `.toastOverlay()` 都讀同一個 coordinator，所以 toast 會在多層同時渲染 — 但只有最上層 sheet 可見，所以使用者只會看到一個。這是可接受的行為，不需為每個 sheet 建獨立 coordinator。

#### A2. 全專案遷移 — 完整 call site 清單

**遷移（26 個 sheet）：**

| # | 檔案 | 類型 | 內容 |
|---|------|------|------|
| 1 | `BookshelfView.swift:93` | sheet | SettingsView |
| 2 | `SyncView.swift:29` | sheet | SettingsView |
| 3 | `KnowledgeGraphView.swift:28` | sheet | WordDetailSheet |
| 4 | `ReaderView.swift:85` | sheet | TOCView |
| 5 | `ReaderView.swift:118` | sheet | SubscriptionPaywallSheet |
| 6 | `ReaderView.swift:121` | sheet | WordDetailSheet |
| 7 | `ReaderView.swift:124` | sheet | ReaderNotebookPicker |
| 8 | `LinkedCardOverlayStack.swift:26` | sheet | WordEditSheet |
| 9 | `StatsPresenter.swift:87` | sheet | ReviewCalendarPresenter |
| 10 | `NotebookListView.swift:137` | sheet | NotebookEditSheet(.create) |
| 11 | `NotebookListView.swift:144` | sheet | NotebookEditSheet(.edit) |
| 12 | `NotebookListView.swift:159` | sheet | ArchivedVocabSheet |
| 13 | `NotebookFilterChip.swift:35` | sheet | NotebookFilterPickerSheet |
| 14 | `TodayReviewView.swift:90` | sheet | LinkReasonSheet |
| 15 | `KGVocabView.swift:63` | sheet | WordDetailSheet |
| 16 | `KGVocabView.swift:160` | sheet | NotebookPickerSheet |
| 17 | `WordDetailSheet.swift:81` | sheet | WordEditSheet |
| 18 | `WordDetailSheet.swift:84` | sheet | AddLinkSheet |
| 19 | `SettingsView.swift:70` | sheet | OptionalIntegrationInfoSheetView |
| 20 | `SettingsView.swift:73` | sheet | SubscriptionPaywallSheet |
| 21 | `ArchivedVocabSheet.swift:73` | sheet | WordDetailSheet |
| 22 | `VocabularyListView+Sheets.swift:15` | sheet | SyncView |
| 23 | `VocabularyListView+Sheets.swift:18` | sheet | SettingsView |
| 24 | `VocabularyListView+Sheets.swift:21` | sheet | ShareSheet |
| 25 | `VocabularyListView+Sheets.swift:24` | sheet | WordDetailSheet |
| 26 | `VocabularyListView+Sheets.swift:39` | sheet | TodayReviewView (iPad/regular) |

**遷移（fullScreenCover，2 個）：**

| # | 檔案 | 內容 |
|---|------|------|
| 27 | `NotebookListView.swift:151` | TodayReviewView |
| 28 | `VocabularyListView+Sheets.swift:28` | TodayReviewView (compact) |

**排除（1 個）：**

| # | 檔案 | 內容 | 原因 |
|---|------|------|------|
| — | `BooksBrowserApp.swift:264` | WelcomeView | 首次啟動 onboarding，不需 toast |

**額外處理：**
- 移除 `WordDetailSheet.swift:80` 手動 `.toastOverlay()` — 改由呈現端的 `.toastSheet()` 掛載
- 移除 `TodayReviewView.swift:86` 手動 `.toastOverlay()` — 同理
- 保留 `BooksBrowserApp.swift:161` root `.toastOverlay()` — 給非 sheet 主畫面用

### B. 通知四級規範

| 級別 | 機制 | 何時用 | 持續時間 | 範例 |
|------|------|--------|---------|------|
| **Toast** | `toastCoordinator.success/error/warning/info` | 使用者主動操作的結果 | success/info 2.5s, warning/error 4s | 「已複製」「已刪除」「儲存失敗」 |
| **Banner** | `AppBanner(message:onRetry:onDismiss:)` | 持續性狀態問題 | 直到問題解決或使用者 dismiss | 「目前沒有網路連線」「同步失敗」「enrichment 錯誤」 |
| **Alert** | `.alert()` | 需使用者決策的阻斷式操作 | 直到使用者回應 | 「刪除帳號？」「登入已過期」 |
| **靜默** | `AppLog` only | 背景自癒操作、非關鍵快取 | — | review push、stats sync、JSON decode |

### C. 通知覆蓋補齊

#### C1. `ModelContext.safeSaveWithToast()` helper

封裝重複 pattern，避免 13+ 處寫同樣的 `if !safeSave()` 邏輯：

```swift
extension ModelContext {
    /// safeSave + toast on failure. Use for user-initiated operations only.
    @discardableResult
    func safeSaveWithToast(
        _ toastCoordinator: AppToastCoordinator,
        file: String = #file, line: Int = #line
    ) -> Bool {
        let ok = safeSave(file: file, line: line)
        if !ok { toastCoordinator.error("儲存失敗") }
        return ok
    }
}
```

#### C2. HIGH — 使用者操作失敗無回饋（必修）

| 位置 | 操作 | 補什麼 |
|------|------|--------|
| `NotebookListCoordinator` — `createNotebook` catch | Notebook 建立失敗 | `toast.error("建立失敗")` |
| `NotebookListCoordinator` — `createNotebook` 成功 | Notebook 建立成功 | `toast.success("已建立")` |
| `NotebookListCoordinator` — `updateNotebook` catch | Notebook 更新失敗 | `toast.error("更新失敗")` |
| `NotebookListCoordinator` — `updateNotebook` 成功 | Notebook 更新成功 | `toast.success("已更新")` |
| `SettingsCoordinator` — `scheduleOptionalIntegrationSave` catch | API key 儲存失敗 | `toast.error("儲存失敗")` |
| `SettingsCoordinator` — `updateTranslationLanguage` catch | 翻譯語言儲存失敗 | `toast.error("設定儲存失敗")` |
| `VocabularyListCoordinator` — `exportCSV/JSON/Anki` nil 回傳 | 匯出檔案寫入失敗 | `toast.error("匯出失敗")` |

**safeSave() → safeSaveWithToast() 替換（使用者主動操作 call sites）：**
- `KGVocabCoordinator` — `handleDeleteTap` / `handleBatchDelete` / `handleBatchArchive` / `handleBatchMove`
- `NotebookListCoordinator` — move entries / create / update / delete notebook
- `ArchivedVocabSheet` — unarchive
- `VocabularyListCoordinator` — `handlePendingRemoval`
- `BookshelfCoordinator` — delete book
- `ReaderVocabularyContext` — save / delete word from reader（line 34, 48）

**safeSave() 保持不變（背景/同步）：**
- `SyncCoordinator` — sync pull
- `TodayReviewState` — 已有檢查
- `ReviewActivityLog` — 背景記錄
- `PDFReaderView` — 自動儲存位置
- `ReaderVocabularyContext:75` — 背景 context save

#### C3. MEDIUM — 正向回饋缺失（建議補）

| 位置 | 操作 | 補什麼 |
|------|------|--------|
| `ArchivedVocabSheet` | unarchive 成功 | `toast.success("已取消封存")` |
| `KGVocabCoordinator` | 單字刪除成功 | `toast.success("已刪除")` |
| `KGVocabCoordinator` | 批次封存成功 | `toast.success("已封存 N 個")` |
| `KGVocabCoordinator` | 移動至筆記本成功 | `toast.success("已移動")` |
| `BookshelfCoordinator` | 書籍刪除成功 | `toast.success("已刪除")` |
| `BookshelfView` | EPUB 匯入成功 | `toast.success("已匯入")` |
| `ICloudDownloadManager` | iCloud 下載失敗 | `toast.warning("iCloud 下載失敗")` |

#### C4. Coordinator toastCoordinator 注入

統一使用 **pass-through 參數 pattern**（與現有 `deleteNotebook(toastCoordinator:)` 一致）。不在 coordinator 上加屬性，而是在每個需要 toast 的方法簽名上加 `toastCoordinator` 參數：

```swift
// 範例：現有 pattern
func deleteNotebook(_ notebook: Notebook, toastCoordinator: AppToastCoordinator) async

// 新增同樣 pattern
func createNotebook(name: String, toastCoordinator: AppToastCoordinator) async
func updateNotebook(_ notebook: Notebook, toastCoordinator: AppToastCoordinator) async
```

需加入 `toastCoordinator` 參數的方法：
- `SettingsCoordinator` — `scheduleOptionalIntegrationSave`、`updateTranslationLanguage`
- `NotebookListCoordinator` — `createNotebook`、`updateNotebook`
- `KGVocabCoordinator` — `handleDeleteTap`、`handleBatchDelete`、`handleBatchArchive`、`handleBatchMove`
- `BookshelfCoordinator` — `deleteBook`
- `VocabularyListCoordinator` — `handlePendingActionTap`（內部呼叫 `handlePendingRemoval`）
- `VocabularyListCoordinator` — `exportCSV`、`exportJSON`、`exportAnki`（匯出失敗時 toast）

呼叫端（View）透過 `@Environment(\.toastCoordinator)` 取得後傳入。

---

## Migration Checklist

1. 建立 `View+ToastSheet.swift`（A1）
2. 建立 `ModelContext.safeSaveWithToast()`（C1）
3. 全專案 28 處 `.sheet(`/`.fullScreenCover(` → `.toastSheet(`/`.toastFullScreenCover(`（A2）
4. 移除 WordDetailSheet/TodayReviewView 手動 `.toastOverlay()`
5. Coordinator 方法加 `toastCoordinator` 參數（C4）
6. 替換使用者操作 call sites 的 `safeSave()` → `safeSaveWithToast()`（C2）
7. 補齊 HIGH 級 catch block toast（C2）
8. 補齊 MEDIUM 級成功回饋（C3）
9. iOS build 驗證
