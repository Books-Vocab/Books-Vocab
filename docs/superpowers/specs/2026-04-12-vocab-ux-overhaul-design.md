# 單字本 UX 重構設計

## 動機

單字本的 UX 有幾個結構性問題：
1. 「待收錄/已收錄」雙 tab 暴露了 sync 實作細節，使用者不需要關心
2. NotebookListView 是扁平 list row，缺乏視覺辨識度和狀態資訊
3. 複習入口分散且行為不一致（書架跨本 vs 單本 toolbar menu）
4. 匯出功能藏太深，使用者不知道存在

## 設計決策摘要

| # | 項目 | 決策 |
|---|------|------|
| 1 | 封面視覺 | 色塊封面 + 可選背景圖片/內建圖案 |
| 2 | 移除 tab selector | VocabularyListView 直接顯示已收錄列表 |
| 3 | 待收錄列表歸屬 | 搬入 SyncView 的 `.ready` phase |
| 4 | 單本複習入口 | 有到期時顯示 banner，平時 toolbar 按鈕 |
| 5 | 未學/到期分開 | 兩層入口都分開，各有獨立按鈕 |
| 6 | 背景圖片來源 | 內建圖庫（SwiftUI 生成）+ 相簿自選（不同步） |
| 7 | 調色盤 | 預設 12 色固定色票 |
| 8 | 匯出位置 | toolbar 按鈕 + 書架卡片 context menu 雙入口 |

---

## 變更 1：NotebookListView 書架化

### 現狀

`NotebookListView` 使用 `NotebookRow`（4px 色條 + 名稱 + 數字 + chevron），`ForEach` 垂直列表。

### 目標

改為 `LazyVGrid` 卡片 grid，每張 `NotebookCard` 顯示：

```
┌──────────────────┐
│ ████████████████ │  ← 色塊封面（notebook color 或自訂圖案/圖片）
│ ████ Self █████ │  ← 白色書名，居中
│ ████████████████ │
│                  │
│  📚 42 個單字     │
│  ▓▓▓▓░░░ 67%    │  ← 複習進度條（ProgressCapsule）
│  ⏰ 5 到期 · 3 未學│
│  ✓ 已同步 · 2天前 │
└──────────────────┘
```

**封面區塊：**
- 預設：notebook color 為純色背景，白色書名居中
- 可選：覆蓋內建圖案（SwiftUI Canvas 生成的幾何/紋理）
- 可選：覆蓋使用者相簿圖片（`PhotosPicker`，裁切後存本地，不同步）
- 封面高度比例約 3:2（橫向），不同於書架的 2:3（直向）

**狀態指標：**
- 卡片數：「42 個單字」
- 複習進度條：`reviewedCount / (reviewedCount + dueCount + unlearnedCount)`，只計算 `shouldAppearInKnowledgeList` 的 entries
- 到期/未學：分開顯示，warning 色 + secondary 色
- 同步狀態：pending count > 0 時顯示「N 待同步」，否則「✓ 已同步」
- 最後活動：相對時間（RelativeDateTimeFormatter）

**Per-notebook 分類計算：**

現有 `computeCounts` 只回傳 cardCount + dueCount。需重寫為完整三分類：

```swift
struct NotebookStats {
    var cardCount: Int = 0
    var dueCount: Int = 0
    var unlearnedCount: Int = 0
    var reviewedCount: Int = 0
    var pendingCount: Int = 0
    var lastActivity: Date?
}

static func computeNotebookStats(_ entries: [VocabularyEntry], pendingEntries: [VocabularyEntry]) -> [String: NotebookStats]
```

分類邏輯復用 `VocabularyEntryPresentation.classifyKnowledgeEntries` 的判斷標準：
- due: `reviewCount > 0 && nextReviewAt <= now`
- unlearned: `reviewCount == 0`（首次 nextReviewAt 預設 distantPast，自動歸入此類）
- reviewed: `reviewCount > 0 && nextReviewAt > now`

單次 O(n) 遍歷，per-notebook 分群。效能注意：entries 數量預期 < 5000，單次 O(n) 可接受。

**Grid 佈局：**
- 復用 `LayoutMode` 的 adaptive 策略
- compact: `GridItem(.adaptive(minimum: 160, maximum: 200))`
- regular: `GridItem(.adaptive(minimum: 200, maximum: 260))`

**互動：**
- 點擊 → NavigationLink 進入 `VocabularyListView`
- 長按 / context menu → 設為使用中、編輯、匯出（CSV/JSON/Anki）、刪除

---

## 變更 2：Notebook 封面系統

### 資料模型

**iOS Notebook model 新增：**
```swift
var coverPattern: String?           // 內建圖案 identifier（同步到後端）
var coverImagePath: String?         // 相簿自選圖片的本地檔案路徑（不同步）
```

注意：自訂圖片不存在 SwiftData `@Model` 的 `Data` 屬性中（避免 `@Query` 時全部載入記憶體）。改為存檔到 app 的 documents directory，model 只存路徑。View 層按需用 `AsyncImage` 或手動載入。

**SwiftData migration：** 兩個新欄位都是 `Optional`，SwiftData 自動 lightweight migration，無需手動 schema version。

**Backend Notebook model 新增：**
```python
cover_pattern: str | None = None   # 內建圖案 identifier
```

**Backend SQLite migration：** `ALTER TABLE notebook ADD COLUMN cover_pattern TEXT`，在 app startup 時執行（與現有 migration 策略一致）。

**API 變更：**
- `NotebookCreateRequest` 新增 `cover_pattern: str | None`
- `NotebookUpdateRequest` 新增 `cover_pattern: str | None = Field(default=None)`
- `NotebookResponse` 新增 `coverPattern: str | None`

**清除 cover_pattern 的 API 契約：** 使用空字串 `""` 表示「清除圖案」（與 `None` = 未傳送區分）。Router 層在收到 `""` 時寫入 `None`。這避免了 Pydantic UNSET 的複雜度，且與現有 color 欄位的 PATCH 語意一致。

**iOS Sync 影響：** 現有 `NotebookListCoordinator.reconcileNotebooks()` 在 pull 時解析 `NotebookResponse` 並更新本地 model。需新增 `coverPattern` 欄位的解析與寫入。Push（create/update）時帶上 `cover_pattern` 參數。

### 預設調色盤（12 色）

前 6 色是現有 `NotebookEditSheet.colorOptions` 的超集，無需資料遷移。

```swift
static let palette: [(name: String, hex: String)] = [
    ("森林", "#5B8C5A"),   ("海洋", "#4A90D9"),
    ("琥珀", "#D4A843"),   ("紫藤", "#A855C7"),
    ("珊瑚", "#D9534F"),   ("石墨", "#6B7280"),
    ("薄荷", "#5CC6B0"),   ("靛藍", "#4F46E5"),
    ("玫瑰", "#E8789A"),   ("焦糖", "#B8763E"),
    ("天空", "#7CB9E8"),   ("薰衣草", "#9B8EC4"),
]
```

### 內建圖案（6 種）

SwiftUI Canvas 生成，不需 bundle 圖片資源：
- `dots`：規則圓點陣列
- `lines`：斜線條紋
- `grid`：格線
- `waves`：波浪
- `circles`：同心圓
- `noise`：隨機點

每個圖案用白色 0.15 opacity 覆蓋在 notebook color 上。

### NotebookEditSheet 改版

現有 `onSave: (String, String?) -> Void` 簽名需擴展。

**新簽名：**
```swift
struct NotebookAppearance {
    let name: String
    let color: String?
    let coverPattern: String?
    let coverImagePath: String?   // nil = 不變，"" = 清除
}

let onSave: (NotebookAppearance) -> Void
```

**Call chain 影響：**
- `NotebookEditSheet.onSave` → `NotebookListCoordinator.createNotebook` / `updateNotebook` → 後端 API
- `NotebookListCoordinator` 的 create/update 方法簽名需配合修改

**UI 改版：**
1. **封面預覽**：即時預覽目前的色彩 + 圖案/圖片組合
2. **調色盤**：12 色 grid（2 行 6 列）
3. **圖案選擇器**：6 個圖案縮圖 + 「無」選項
4. **自訂圖片**：PhotosPicker 按鈕，已選時顯示縮圖 + 移除按鈕

---

## 變更 3：待收錄列表搬入 SyncView

### 現狀

`VocabularyListView` 有 `VocabTabSelector`（待收錄 / 已收錄），`PendingVocabPresenter` 在 tab 0。

### 目標

- 移除 `VocabTabSelector`
- `VocabularyListView` 直接渲染 `KGVocabView`
- `PendingVocabPresenter` 移入 `SyncPresenter` 的 `.ready` phase
- SyncPresenter `.ready` 佈局：header hero → pending list → pipeline steps → action area

### SyncPresenter 佈局重構

現有 SyncPresenter 用 `VStack + Spacer + actionArea`（非 ScrollView）。嵌入 pending list 後需改為 ScrollView：

```
ScrollView {
    VStack {
        headerView           ← 保持
        pendingListSection   ← 新增：VocabCard 包裹 WordRow 列表
        stepsSection         ← 保持
        summaryCard          ← 保持
    }
}

// sticky bottom
actionArea                   ← safeAreaInset(edge: .bottom)
```

pending list 自帶 scroll（在 ScrollView 內），不需獨立限高。action area 用 `.safeAreaInset(edge: .bottom)` 固定在底部，不隨滾動。

### SyncView 新佈局（.ready phase）

```
┌─────────────────────────┐
│ 🔄 N 個待處理動作        │  ← VocabStatusHero（保持）
│    12 新增  2 刪除       │  ← VocabToneChip（保持）
├─────────────────────────┤
│ ┌─────────────────────┐ │
│ │ WordRow: apple      │ │  ← 復用現有 WordRow + action button
│ │ WordRow: banana     │ │
│ │ WordRow: cherry     │ │
│ │ ...                 │ │
│ └─────────────────────┘ │
├─────────────────────────┤
│ Pipeline steps          │  ← 現有 step rows（保持）
├─────────────────────────┤
│     [開始同步]           │  ← 固定底部 action area
└─────────────────────────┘
```

### SyncPresenterState 擴展

新增 pending list 資料：
```swift
struct SyncPresenterState {
    // ... existing fields ...
    let pendingRows: [PendingVocabPresenterState.RowItem]  // 復用現有 RowItem
}
```

### SyncView 新增職責

SyncView 需新增 pending entries 的 action 處理（row tap → show detail、action tap → delete/restore），從 `VocabularyListCoordinator` 搬移對應邏輯。

### 影響範圍

- `VocabularyListView.swift`：移除 `selectedTab`、tab 相關邏輯，直接渲染 KGVocabView
- `VocabularyListView+State.swift`：移除 `presenterState`、`pendingPresenterState`、`routedContent` 中的 tab 路由、`filteredPendingEntries`
- `VocabularyListPresenter.swift`：移除 `VocabTabSelector`，簡化為搜尋 + content
- `VocabularyListView+Toolbar.swift`：移除 `selectedTab` 依賴，匯出改為已收錄單字
- `SyncView.swift`：新增 pending entries 處理
- `SyncPresenter.swift`：改為 ScrollView + sticky bottom，`.ready` phase 嵌入 pending list
- `SyncPresenterState`：新增 pendingRows
- `PendingVocabPresenter.swift`：保留元件，從 SyncPresenter 調用

---

## 變更 4：複習入口統一

### 書架層（NotebookListView）

現有 banner 改為分開顯示。觸發條件從 `totalDueCount > 0` 改為 `totalDueCount > 0 || totalUnlearnedCount > 0`：

```
┌────────────────────────────────────────────┐
│  今日複習                      [篩選單字本]  │
│  5 張到期 · 3 未學習                        │
│                  [到期複習]  [未學複習]       │
└────────────────────────────────────────────┘
```

- 兩個按鈕各自啟動對應 scope 的 `TodayReviewSession`
- NotebookFilterChip 保持
- 需新增 per-notebook unlearnedCount 計算（見變更 1 的 `computeNotebookStats`）

### 單本層（VocabularyListView）

**方案 C：banner + toolbar**

- **有到期/未學時**：列表頂部顯示 banner（與書架 banner 同樣式但 scope 限本本，無 NotebookFilterChip）
- **無到期/未學時**：toolbar 保留 review 按鈕（可手動啟動全部複習）
- Banner 和 toolbar 進入同一個 `TodayReviewView`，只是 filter scope 不同

### 新增 VocabReviewBanner 元件

提取為獨立元件，書架和單本共用：

```swift
struct VocabReviewBanner: View {
    let dueCount: Int
    let unlearnedCount: Int
    let onStartDue: () -> Void
    let onStartUnlearned: () -> Void
    var filterContent: AnyView? = nil  // 書架層放 NotebookFilterChip
}
```

---

## 變更 5：匯出功能雙入口

### 語意變更

原本匯出只在 pending tab，匯出範圍是 `pendingEntries`（未同步的 entries）。移除 pending tab 後，匯出改為已收錄單字。理由：已收錄單字是使用者的核心資料，pending entries 是暫態。Pending entries 仍可在 SyncView 查看。

### 單本 toolbar

在 VocabularyListView toolbar 顯示匯出按鈕：
- `square.and.arrow.up` icon，點擊展開 Menu（CSV / JSON / Anki TSV）
- 匯出範圍：該本所有 synced + non-deleted + non-archived 的 entries

### 書架 context menu

`NotebookCard` 長按 context menu 新增：
- 「匯出」子選單（CSV / JSON / Anki TSV）
- 匯出範圍：同上

---

## 變更 6：元件復用

### 新增 ProgressCapsule

新建獨立元件（非從 BookCard 提取，因 BookCard 的進度條是內嵌實作，提取反而增加耦合）：

```swift
struct ProgressCapsule: View {
    let progress: Double  // 0.0 - 1.0
    let label: String?    // e.g. "67%"
    var fillColor: Color
    var trackColor: Color
    var height: CGFloat = 6
}
```

使用處：
- `NotebookCard`：複習進度 = reviewedCount / totalSyncedCount

### VocabReviewBanner（見變更 4）

書架和單本共用。

---

## 不做的事

- 不改變 `TodayReviewView` 的複習邏輯或 UI
- 不改變 pipeline 流程
- 不改變後端 sync 協議結構（僅新增 `cover_pattern` 欄位）
- 不做 notebook 排序拖曳（用 context menu 保持現狀）
- 不做跨 notebook 移動單字（已在之前設計中明確砍掉）
- 自訂封面圖片不同步到後端
- 不重構 BookCard 的進度條（ProgressCapsule 是獨立新元件）

---

## 風險與緩解

| 風險 | 緩解 |
|------|------|
| 書架 grid 在少量 notebook 時顯得空曠 | 加入「新增單字本」佔位卡片 |
| 自訂圖片佔用儲存空間 | 裁切後壓縮為 JPEG，限制 max 500KB |
| 移除 pending tab 後使用者找不到 pending 狀態 | sync 按鈕 badge 數字提示 |
| NotebookEditSheet 變複雜 | 分段呈現：基本資訊 → 外觀自訂 |
| per-notebook 分類計算效能 | 單次 O(n) 遍歷，entries < 5000 可接受 |
| SwiftData model 新增欄位 | Optional 欄位，自動 lightweight migration |
| API cover_pattern 清除語意 | 空字串 = 清除，None = 未傳送 |
