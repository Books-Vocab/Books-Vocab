# 總覽 Tab 提升 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將「總覽」從單字本內的第三個 tab 提升為頂層 TabView tab，支援 notebook 篩選。

**Architecture:** ContentView TabView 新增第三個 tab → 新建 `OverviewTab` 作為容器，內嵌 `NotebookFilterChip`（復用現有元件）+ 改造後的 `StatsPresenter`。`VocabularyListView` 移除第三個 tab。`StatsPresenter` 改為接收 `NotebookFilter` 來動態過濾 entries 和 review records。

**Tech Stack:** SwiftUI, SwiftData, existing VocabSkin design system

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `Views/Vocabulary/Scenes/OverviewTab.swift` | 頂層總覽 tab 容器：NavigationStack + filter chip + StatsPresenter |
| Modify | `Views/Vocabulary/Scenes/StatsPresenter.swift` | 移除 `allEntries` init param，改為內部 `@Query` + filter |
| Modify | `Views/Vocabulary/VocabularyListView+State.swift:70-81,112-131` | 移除第三個 tab option + 路由 |
| Modify | `ContentView.swift:36-43` | TabView 新增第三個 tab |
| Modify | `Views/Vocabulary/Scenes/VocabularyListPresenter.swift` | 搜尋欄位邏輯（只剩 2 tab，searchPrompt 簡化） |

---

### Task 1: 建立 OverviewTab 容器

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Scenes/OverviewTab.swift`

- [ ] **Step 1: 建立 OverviewTab.swift**

```swift
//
//  OverviewTab.swift
//  BooksBrowser
//
//  頂層總覽 tab — 篩選器 + 統計儀表板。

import SwiftUI
import SwiftData

struct OverviewTab: View {
    @Environment(\.authManager) private var authManager
    @Environment(\.modelContext) private var modelContext
    @Environment(\.vocabSkin) private var skin

    @State private var filter = NotebookFilter.load()

    var body: some View {
        NavigationStack {
            if authManager.isLoggedIn || authManager.isDemoMode {
                StatsPresenter(filter: filter)
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            NotebookFilterChip(filter: $filter)
                        }
                    }
                    .navigationTitle("總覽".localized)
                    .navigationBarTitleDisplayMode(.large)
            } else {
                loggedOutState
            }
        }
    }

    @ViewBuilder
    private var loggedOutState: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                AppEmptyStateCard(
                    title: "需登入帳號".localized,
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: "總覽功能需要登入帳號後才能存取您的雲端資料。".localized
                )
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppMetrics.spacingMedium)
        }
        .navigationTitle("總覽".localized)
        .navigationBarTitleDisplayMode(.large)
    }
}
```

- [ ] **Step 2: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0（新檔案尚未被引用，不影響現有功能）

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/OverviewTab.swift
git commit -m "ios: 新增 OverviewTab 容器（尚未接入 TabView）"
```

---

### Task 2: 改造 StatsPresenter — 接收 NotebookFilter

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift`

目前 `StatsPresenter` 接收 `allEntries: [VocabularyEntry]`，由外部傳入。改為內部 `@Query` 自行取資料，用 `NotebookFilter` 過濾。

- [ ] **Step 1: 改造 StatsPresenter**

將 `init(allEntries:)` 改為 `init(filter:)`：

```swift
struct StatsPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let filter: NotebookFilter

    @Query(filter: #Predicate<VocabularyEntry> {
        $0.syncStatus == 1 &&
        $0.actionType != "delete"
    })
    private var syncedEntries: [VocabularyEntry]

    @Query var reviewRecords: [ReviewRecord]

    @State private var summary: StatsPresentation.Summary?
    @State private var showCalendar = false

    private static let sixMonthsAgo = Calendar.current.date(byAdding: .month, value: -6, to: Date()) ?? Date()

    init(filter: NotebookFilter = NotebookFilter()) {
        self.filter = filter
        let cutoff = Self.sixMonthsAgo
        _reviewRecords = Query(
            filter: #Predicate<ReviewRecord> { $0.reviewedAt > cutoff },
            sort: \ReviewRecord.reviewedAt,
            order: .reverse
        )
    }

    // ... body 不變 ...

    private var filteredEntries: [VocabularyEntry] {
        filter.isFiltered
            ? syncedEntries.filter { filter.matches($0.notebookId) }
            : syncedEntries
    }

    private var filteredReviewRecords: [ReviewRecord] {
        filter.isFiltered
            ? reviewRecords.filter { filter.matches($0.notebookId) }
            : reviewRecords
    }

    private func recompute() {
        summary = StatsPresentation.buildSummary(
            from: filteredEntries,
            reviewRecords: filteredReviewRecords
        )
    }
```

同時更新 `graphEntrySection`：將 `allEntries` 改為 `filteredEntries`：

```swift
private var graphEntrySection: some View {
    NavigationLink {
        KnowledgeGraphView(allEntries: filteredEntries)
    } label: {
        // ... 不變 ...
    }
}
```

更新 `onChange` triggers — 加上 filter 變化時 recompute：

```swift
.onChange(of: filter) { _, _ in
    recompute()
}
```

- [ ] **Step 2: 更新 VocabularyListView+State.swift 中的呼叫處**

`VocabularyListView+State.swift:127` 的 `StatsPresenter(allEntries: allEntries)` 暫時改為 `StatsPresenter(filter: NotebookFilter(selectedIds: [notebookId]))`，讓它在單字本內仍能工作（下一個 Task 會移除整段）。

- [ ] **Step 3: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift
git add ios/BooksBrowser/Views/Vocabulary/VocabularyListView+State.swift
git commit -m "ios: StatsPresenter 改為 filter-driven，支援 notebook 篩選"
```

---

### Task 3: ContentView 新增總覽 Tab + 移除舊 tab

**Files:**
- Modify: `ios/BooksBrowser/ContentView.swift:36-43`
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+State.swift:70-81,112-131`

- [ ] **Step 1: ContentView 加第三個 Tab**

`ContentView.swift:36-43` 的 TabView 改為：

```swift
TabView {
    Tab("書庫".localized, systemImage: "books.vertical") {
        BookshelfView()
    }
    Tab("生詞庫".localized, systemImage: "character.book.closed") {
        NotebookListView()
    }
    Tab("總覽".localized, systemImage: "chart.bar") {
        OverviewTab()
    }
}
```

- [ ] **Step 2: VocabularyListView+State 移除第三個 tab**

`tabOptions` 改為只有 2 個 tab（移除 `id: 2` 的「總覽」項目）：

```swift
var tabOptions: [VocabTabOption<Int>] {
    [
        .init(id: 0, title: "待收錄".localized, count: pendingCount, systemImage: "tray"),
        .init(
            id: 1,
            title: "知識庫".localized,
            count: syncedKnowledgeEntries.count,
            systemImage: "books.vertical"
        ),
    ]
}
```

`routedContent` 移除 `selectedTab == 2` 的分支：

```swift
@ViewBuilder
var routedContent: some View {
    Group {
        if selectedTab == 0 {
            PendingVocabPresenter(
                state: pendingPresenterState,
                onRowTapped: handlePendingRowTap,
                onActionTapped: handlePendingActionTap,
                onSwitchToKnowledge: switchToKnowledgeTab
            )
        } else if !authManager.isLoggedIn {
            loggedOutState
        } else {
            KGVocabView(searchText: $searchText, notebookId: notebookId)
        }
    }
    .transition(.contentSwap)
}
```

`showsSearchField` 簡化（不再需要 tab 2 判斷）：

```swift
var showsSearchField: Bool {
    selectedTab == 0 || (selectedTab == 1 && authManager.isLoggedIn)
}
```

- [ ] **Step 3: 移除 loggedOutState 中的「總覽」文字引用**

`VocabularyListView+State.swift:142` 的 description 從 `"知識庫與總覽功能需要登入帳號..."` 改為 `"知識庫功能需要登入帳號後才能存取您的雲端資料。"`

- [ ] **Step 4: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/ContentView.swift
git add ios/BooksBrowser/Views/Vocabulary/VocabularyListView+State.swift
git commit -m "ios: 總覽提升為頂層 tab + 從單字本移除舊 tab"
```

---

### Task 4: Preview + 清理

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/OverviewTab.swift` (加 Preview)
- Modify: `ios/BooksBrowser/ContentView.swift` (更新 Preview modelContainer)
- Check: `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter+Preview.swift` (移除 totalStats 引用如果有)

- [ ] **Step 1: OverviewTab 加 Preview**

```swift
#Preview {
    OverviewTab()
        .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
}
```

- [ ] **Step 2: ContentView Preview 更新**

確保 `ContentView` Preview 的 `modelContainer` 包含 `ReviewRecord.self` 和 `Notebook.self`：

```swift
#Preview {
    ContentView()
        .modelContainer(for: [Book.self, VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
}
```

- [ ] **Step 3: 搜尋 StatsPresenter 的舊 init 引用**

Grep `StatsPresenter(allEntries` 確認沒有殘留呼叫。若 `SyncPresenter+Preview.swift` 或其他 Preview 檔案引用了，一併更新為 `StatsPresenter(filter:)`。

- [ ] **Step 4: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "ios: 總覽 tab Preview + 清理舊引用"
```

---

### Task 5: Localisation

**Files:**
- Modify: `ios/BooksBrowser/zh-Hant.lproj/Localizable.strings`
- Modify: `ios/BooksBrowser/en.lproj/Localizable.strings`
- Modify: `ios/BooksBrowser/ja.lproj/Localizable.strings`
- Modify: `ios/BooksBrowser/ko.lproj/Localizable.strings`
- Modify: `ios/BooksBrowser/zh-Hans.lproj/Localizable.strings`

- [ ] **Step 1: 新增/更新 localization strings**

新增 key（如果 `"總覽"` 已存在則確認即可）：
- `"總覽功能需要登入帳號後才能存取您的雲端資料。"` — 各語言翻譯

更新被修改的 key：
- `"知識庫與總覽功能需要登入帳號後才能存取您的雲端資料。"` → `"知識庫功能需要登入帳號後才能存取您的雲端資料。"`

- [ ] **Step 2: 編譯驗證**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/*.lproj/Localizable.strings
git commit -m "ios: 總覽 tab 提升 — localization 更新"
```
