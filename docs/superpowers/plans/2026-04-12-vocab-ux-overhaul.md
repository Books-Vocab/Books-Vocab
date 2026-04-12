# 單字本 UX 重構 Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 重構單字本 UX — 書架化 notebook 列表、移除 pending tab、統一複習入口、匯出雙入口。
**Architecture:** iOS SwiftUI 前端重構為主，後端新增 cover_pattern 欄位。不改變 sync 協議結構。
**Tech Stack:** SwiftUI + SwiftData (iOS)、FastAPI + SQLModel (Backend)

---

### Task 1: Backend — Notebook cover_pattern 欄位

**Files:**
- Modify: `backend/src/kg/notebook.py`
- Modify: `backend/src/kg/api_models.py`
- Modify: `backend/src/kg/routers/notebook.py`
- Test: `backend/tests/test_notebook.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_create_notebook_with_cover_pattern(client, auth_headers):
    resp = client.post("/api/notebooks", json={"name": "Test", "cover_pattern": "dots"}, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["coverPattern"] == "dots"

def test_update_notebook_cover_pattern(client, auth_headers):
    # create
    resp = client.post("/api/notebooks", json={"name": "Test"}, headers=auth_headers)
    nb_id = resp.json()["id"]
    # set pattern
    resp = client.patch(f"/api/notebooks/{nb_id}", json={"cover_pattern": "waves"}, headers=auth_headers)
    assert resp.json()["coverPattern"] == "waves"
    # clear pattern with empty string
    resp = client.patch(f"/api/notebooks/{nb_id}", json={"cover_pattern": ""}, headers=auth_headers)
    assert resp.json()["coverPattern"] is None

def test_update_notebook_cover_pattern_not_sent(client, auth_headers):
    resp = client.post("/api/notebooks", json={"name": "Test", "cover_pattern": "dots"}, headers=auth_headers)
    nb_id = resp.json()["id"]
    # update only name, cover_pattern should remain
    resp = client.patch(f"/api/notebooks/{nb_id}", json={"name": "Renamed"}, headers=auth_headers)
    assert resp.json()["coverPattern"] == "dots"
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_notebook.py -v -k "cover_pattern"`
Expected: FAIL

- [ ] **Step 3: 實作**
  - `notebook.py`: Notebook model 新增 `cover_pattern: str | None = None`
  - `api_models.py`:
    - `NotebookCreateRequest` 新增 `cover_pattern: str | None = None`
    - `NotebookUpdateRequest` 新增 `cover_pattern: str | None = None`
    - `NotebookResponse` 新增 `coverPattern: str | None = None`
  - `routers/notebook.py`:
    - `_notebook_response()` 新增 `coverPattern=nb.cover_pattern`
    - create endpoint: 傳 `cover_pattern` 給 `nb_store.create()`
    - update endpoint: 處理 `cover_pattern`，空字串 → `None`（清除），`None` → 不更新

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_notebook.py -v`

- [ ] **Step 5: Commit**
`api: notebook — add cover_pattern field for bookshelf covers`

---

### Task 2: iOS — Notebook model + ProgressCapsule + NotebookCard 元件

**Files:**
- Modify: `ios/BooksBrowser/Models/Notebook.swift`
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/ProgressCapsule.swift`
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookCard.swift`
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookCoverPatterns.swift`

- [ ] **Step 1: Notebook model 新增欄位**
```swift
// Notebook.swift 新增：
var coverPattern: String?
var coverImagePath: String?
```

- [ ] **Step 2: 建立 ProgressCapsule 元件**
```swift
struct ProgressCapsule: View {
    let progress: Double
    let label: String?
    var fillColor: Color
    var trackColor: Color
    var height: CGFloat = 6

    var body: some View {
        // Capsule track + fill overlay + optional label
    }
}
```

- [ ] **Step 3: 建立 NotebookCoverPatterns**
6 種 SwiftUI Canvas 生成的圖案（dots/lines/grid/waves/circles/noise），封裝為 `NotebookCoverPattern` enum + `patternView(color:)` 方法。

- [ ] **Step 4: 建立 NotebookCard 元件**
```swift
struct NotebookCard: View {
    let name: String
    let color: Color?
    let coverPattern: String?
    let coverImagePath: String?
    let cardCount: Int
    let dueCount: Int
    let unlearnedCount: Int
    let reviewedCount: Int
    let pendingCount: Int
    let lastActivity: Date?
    let isActive: Bool
}
```
顯示：封面（色塊 + 可選圖案/圖片）、書名、卡片數、ProgressCapsule、到期/未學、同步狀態、最後活動。

- [ ] **Step 5: Preview 驗證**
加入 `#Preview` 確認各狀態組合渲染正確。

- [ ] **Step 6: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 7: Commit**
`ios: add NotebookCard, ProgressCapsule, cover patterns`

---

### Task 3: iOS — VocabReviewBanner 元件

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/VocabReviewBanner.swift`

- [ ] **Step 1: 建立 VocabReviewBanner**
```swift
struct VocabReviewBanner<FilterContent: View>: View {
    let dueCount: Int
    let unlearnedCount: Int
    let onStartDue: () -> Void
    let onStartUnlearned: () -> Void
    @ViewBuilder let filterContent: FilterContent

    var body: some View {
        // VocabCard 包裹：title "今日複習"、counts、兩個 borderedProminent 按鈕
    }
}
```

- [ ] **Step 2: Preview 驗證**

- [ ] **Step 3: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 4: Commit**
`ios: add VocabReviewBanner shared component`

---

### Task 4: iOS — NotebookListView 書架化 + 複習入口

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`
- Delete: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookRow.swift`（或保留但不再使用）
- Modify: `ios/BooksBrowser/Platform/LayoutMode.swift`

- [ ] **Step 1: LayoutMode 新增 notebookGridItem**
```swift
var notebookGridItem: GridItem {
    switch self {
    case .compact: return GridItem(.adaptive(minimum: 160, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
    case .regular: return GridItem(.adaptive(minimum: 200, maximum: 260), spacing: AppShellMetrics.sectionSpacing)
    }
}
```

- [ ] **Step 2: 重寫 computeCounts → computeNotebookStats**
替換現有 `computeCounts` 為 `computeNotebookStats`，回傳 `[String: NotebookStats]`，包含 cardCount/dueCount/unlearnedCount/reviewedCount/pendingCount/lastActivity。

- [ ] **Step 3: 重寫 NotebookListView body**
- 將 `ForEach` + `NotebookRow` 替換為 `LazyVGrid` + `NotebookCard`
- 加入「新增單字本」佔位卡片（虛線邊框 + plus icon）
- context menu 新增匯出選項
- 複習 banner 改用 `VocabReviewBanner`，分開 due/unlearned

- [ ] **Step 4: 更新 banner 觸發條件**
從 `totalDueCount > 0` 改為 `totalDueCount > 0 || totalUnlearnedCount > 0`。

- [ ] **Step 5: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 6: Commit**
`ios: notebook bookshelf grid with NotebookCard + review banner`

---

### Task 5: iOS — NotebookEditSheet 改版

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookEditSheet.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListCoordinator.swift`（如存在，或在 NotebookListView 內）

- [ ] **Step 1: 定義 NotebookAppearance struct**
```swift
struct NotebookAppearance {
    let name: String
    let color: String?
    let coverPattern: String?
    let coverImagePath: String?
}
```

- [ ] **Step 2: 重寫 NotebookEditSheet**
- 封面預覽區
- 名稱輸入
- 12 色調色盤（2 行 6 列 grid）
- 6 圖案選擇器 + 「無」
- PhotosPicker 自訂圖片（壓縮為 JPEG ≤ 500KB，存到 documents dir）
- onSave 改為 `(NotebookAppearance) -> Void`

- [ ] **Step 3: 更新 NotebookListView 呼叫端**
更新 `NotebookListView` 中的 `.toastSheet` 呼叫，適配新 onSave 簽名。coordinator create/update 方法傳遞 cover_pattern。

- [ ] **Step 4: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 5: Commit**
`ios: redesign NotebookEditSheet with color palette + cover patterns`

---

### Task 6: iOS — 移除 pending tab + SyncView 整合

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+State.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Toolbar.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/VocabularyListPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/SyncView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter+Header.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListCoordinator.swift`

- [ ] **Step 1: VocabularyListView — 移除 tab**
- 移除 `selectedTab` state
- 移除 `VocabularyListPresenter` 中的 `VocabTabSelector`
- body 直接渲染 `KGVocabView`（或 loggedOutState）
- 保持 search field

- [ ] **Step 2: VocabularyListView+State — 清理**
- 移除 `presenterState`、`tabOptions`、`pendingPresenterState`
- 移除 `routedContent` 的 tab 路由
- 移除 `filteredPendingEntries`、`pendingCount`（移到 SyncView）
- 保留 `pendingEntries` 計算（toolbar badge 仍需要）

- [ ] **Step 3: VocabularyListView+Toolbar — 調整**
- 移除 `selectedTab` 參數
- 匯出改為匯出 synced entries（而非 pending）
- 匯出按鈕始終顯示（在已收錄列表上）

- [ ] **Step 4: SyncPresenter — 改為 ScrollView + 嵌入 pending list**
- body 改為 `ScrollView { VStack { ... } }` + `.safeAreaInset(edge: .bottom) { actionArea }`
- `.ready` phase 在 header 下方嵌入 pending list section
- 復用 `PendingVocabPresenterState.RowItem` 和 `WordRow`

- [ ] **Step 5: SyncView — 新增 pending 處理**
- 新增 pending row tap / action callbacks
- 傳遞 pending rows 到 SyncPresenterState

- [ ] **Step 6: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 7: Commit**
`ios: remove pending tab, integrate into SyncView`

---

### Task 7: iOS — 單本複習入口 (banner + toolbar)

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Toolbar.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`

- [ ] **Step 1: 單本 review banner**
在 VocabularyListView（或 KGVocabView 頂部）加入 `VocabReviewBanner`，scope 為該 notebook 的 entries。只在 dueCount > 0 || unlearnedCount > 0 時顯示。

- [ ] **Step 2: toolbar review 按鈕**
保留 toolbar review 按鈕，改為獨立 `play.fill` icon（不藏在 menu），分 due/unlearned。在 banner 不顯示時（無到期無未學）仍可用（啟動 reviewed entries 的複習）。

- [ ] **Step 3: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 4: Commit**
`ios: unified review entry — banner + toolbar for single notebook`

---

### Task 8: iOS — Notebook sync cover_pattern 整合

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListCoordinator.swift`（或 reconcile 邏輯所在）
- Modify: `ios/BooksBrowser/Services/KGService.swift`（或 API 呼叫所在）

- [ ] **Step 1: Sync pull — 解析 coverPattern**
在 notebook reconcile 邏輯中，從 `NotebookResponse` 讀取 `coverPattern` 並寫入本地 Notebook model。

- [ ] **Step 2: Sync push — 帶上 cover_pattern**
create/update notebook 的 API 呼叫中帶上 `cover_pattern` 參數。

- [ ] **Step 3: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 4: Commit**
`ios: sync cover_pattern for notebook covers`

---

### Task 9: 全量 Build + 後端 Test

- [ ] **Step 1: iOS full build**
Run: `./ops/ios_build.sh`

- [ ] **Step 2: Backend full test**
Run: `cd backend && python -m pytest tests/ -v`

- [ ] **Step 3: 修復任何 failure**

- [ ] **Step 4: Final commit if needed**
