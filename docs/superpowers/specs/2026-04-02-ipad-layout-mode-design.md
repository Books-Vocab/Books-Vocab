# iPad Layout Mode — Design Spec

## 問題

iPad regular width 下的單字本體驗跟 iPhone 完全一樣：detail 用 sheet 彈出，浪費大螢幕空間。macOS 已有 side panel（`MacDetailState` + `safeAreaInset`），但 iPad 無法享用，因為呈現策略是 `#if os()` compile-time 分支而非 runtime layout 判斷。

同時，`horizontalSizeClass` 的 compact/regular 判斷散落在 4 個檔案，沒有統一收口。

## 目標

1. iPad regular width 獲得跟 macOS 一致的 side panel 體驗（word detail + review）
2. 建立 `LayoutMode` enum 統一收口所有 compact/regular 判斷
3. `platformContentMaxWidth` 跟隨 LayoutMode 動態調整

## 不做

- 三檔制 LayoutMode（compact/regular/expansive）— 目前沒有消費場景
- `NavigationSplitView` — 改動過大，side panel 已足夠
- 改動 iOS-only 功能門控（Reader/Bookshelf 整檔 `#if os(iOS)` 保持不變）
- 改動 macOS-only chrome（keyboard handler 保持原位）

## 前置條件

依賴已完成的 platform-adapter-consolidation（commit `b60edb6`），包含 `DetailRouting` protocol、`SheetDetailRouter`、`MacDetailState`、`PlatformCompatibility` modifiers。

---

## Part A：LayoutMode Enum

### 設計

```swift
// Platform/LayoutMode.swift
import SwiftUI

enum LayoutMode: Equatable {
    case compact
    case regular

    init(horizontalSizeClass: UserInterfaceSizeClass?) {
        #if os(macOS)
        self = .regular
        #else
        self = (horizontalSizeClass == .compact) ? .compact : .regular
        #endif
    }
}
```

macOS 永遠是 `.regular`（compile-time 已知），iOS 根據 `horizontalSizeClass` 決定。

### LayoutMode 提供的 adaptive 值

```swift
extension LayoutMode {
    /// 內容最大寬度（取代 platformContentMaxWidth 的硬編碼 600）
    var contentMaxWidth: CGFloat {
        switch self {
        case .compact: return .infinity  // compact 螢幕不需限制
        case .regular: return 720        // regular 放寬到 720（iPad 12.9" 有 1024pt 寬）
        }
    }

    /// 是否使用 inline detail panel（而非 sheet）
    var usesInlineDetail: Bool {
        self == .regular
    }

    /// 書架封面高度
    var bookshelfCoverHeight: CGFloat {
        switch self {
        case .compact: return AppBookshelfMetrics.coverHeightCompact
        case .regular: return AppBookshelfMetrics.coverHeightRegular
        }
    }

    /// 書架 grid item
    var bookshelfGridItem: GridItem {
        switch self {
        case .compact: return GridItem(.adaptive(minimum: 150, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
        case .regular: return GridItem(.adaptive(minimum: 180, maximum: 240), spacing: AppShellMetrics.sectionSpacing)
        }
    }
}
```

---

## Part B：合併 DetailRouter

### 問題分析

`SheetDetailRouter`（iOS）和 `MacDetailState`（macOS）的邏輯**完全相同**（同 properties、同 methods），只差 `#if os()` guard。差異全在 view 層的呈現方式。

### 設計

1. 移除 `MacDetailState.swift`
2. 移除 `SheetDetailRouter` 的 `#if os(iOS)` guard
3. 重新命名為 `DetailRouter`（不是 protocol，是 concrete class）
4. 保留 `DetailRouting` protocol 不變（消費端繼續面向 protocol）

```swift
// Platform/DetailRouter.swift 修改後

@MainActor protocol DetailRouting: AnyObject, Observable { /* 不變 */ }

// 移除 #if os(iOS)
@Observable @MainActor
final class DetailRouter: DetailRouting {
    var selectedEntry: VocabularyEntry?
    var activeReviewSession: TodayReviewSession?
    var contextEntries: [VocabularyEntry] = []
    var hasDetail: Bool { selectedEntry != nil || activeReviewSession != nil }

    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry]) {
        activeReviewSession = nil
        selectedEntry = entry
        contextEntries = allEntries
    }

    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry]) {
        selectedEntry = nil
        activeReviewSession = session
        contextEntries = allEntries
    }

    func dismiss() {
        selectedEntry = nil
        activeReviewSession = nil
        contextEntries = []
    }
}
```

---

## Part C：NotebookListView 統一呈現邏輯

### 現狀

```
#if os(iOS)
  @State sheetRouter = SheetDetailRouter()
  → .environment(\.detailRouter, sheetRouter)
  → .toastSheet(word detail)
  → .platformFullScreenCover(compact review)
  → .toastSheet(regular review)
#elseif os(macOS)
  @State macDetail = MacDetailState()
  → .environment(\.detailRouter, macDetail)
  → .safeAreaInset(trailing: macDetailPanel)
  → .toastSheet(edit sheet)
#endif
```

### 改為

```
@State detailState = DetailRouter()
let layoutMode = LayoutMode(horizontalSizeClass: sizeClass)

→ .environment(\.detailRouter, detailState)
→ if layoutMode.compact:
    .toastSheet(word detail)
    .platformFullScreenCover(review)
  else (regular — iPad + macOS):
    .safeAreaInset(trailing: detailPanel)
    .toastSheet(edit sheet)
```

**關鍵變化**：iPad regular width 從走「sheet 路線」切換到「side panel 路線」，跟 macOS 一致。

### Detail Panel（從 macOS-only 改為 regular-only）

`macDetailPanel` 重新命名為 `inlineDetailPanel`，移除 `#if os(macOS)` guard。內容不變：

- 優先顯示 review session → `TodayReviewView`
- 其次顯示 word detail → `VocabOverlayHeader` + `WordDetailSheet`
- 寬度：`minWidth: 350, idealWidth: 420, maxWidth: 600`（收進 LayoutMode 或 VocabSkin.Metrics）

---

## Part D：遷移其他 sizeClass 消費點

| 檔案 | 現狀 | 改為 |
|------|------|------|
| `BookshelfView.swift` | `sizeClass == .regular` 算 columns/coverHeight | `LayoutMode` 的 `.bookshelfGridItem` / `.bookshelfCoverHeight` |
| `VocabularyListView.swift` | 傳 `sizeClass` 給 `VocabularyListSheets` | 傳 `LayoutMode`（但目前 Sheets 不用 sizeClass 決定任何事，可直接移除參數） |
| `ReaderViewPresenter+Headers.swift` | `sizeClass == .regular` 決定 titleMaxWidth | `LayoutMode`（Reader 是 `#if os(iOS)` only，所以永遠是 iOS 的 compact/regular） |
| `NotebookListView.swift` | 見 Part C | 見 Part C |

### `platformContentMaxWidth` 更新

```swift
// 現行：
func platformContentMaxWidth(_ width: CGFloat = 600) -> some View

// 新增 LayoutMode-aware 版本：
func platformContentMaxWidth(for layoutMode: LayoutMode) -> some View {
    self.frame(maxWidth: layoutMode.contentMaxWidth)
        .frame(maxWidth: .infinity)
}
```

保留舊簽名做 backward compat（只有 1 處呼叫，遷移後可刪）。

---

## 影響範圍

### 新增檔案
- `Platform/LayoutMode.swift`

### 修改檔案
- `Platform/DetailRouter.swift` — 移除 `#if os(iOS)`，`SheetDetailRouter` → `DetailRouter`
- `Platform/PlatformCompatibility.swift` — 新增 LayoutMode-aware `platformContentMaxWidth`
- `Views/Vocabulary/Scenes/NotebookListView.swift` — 合併 iOS/macOS 分支為 LayoutMode 分支
- `Views/Vocabulary/Scenes/TodayReviewPresenter.swift` — 用 LayoutMode-aware `platformContentMaxWidth`
- `Views/Bookshelf/BookshelfView.swift` — sizeClass → LayoutMode
- `Views/Vocabulary/VocabularyListView.swift` — 移除 sizeClass 傳遞
- `Views/Vocabulary/VocabularyListView+Sheets.swift` — 移除 sizeClass 參數
- `Views/Reader/ReaderViewPresenter+Headers.swift` — sizeClass → LayoutMode

### 刪除檔案
- `Views/Vocabulary/MacDetailState.swift` — 合併進 `DetailRouter.swift`

### 不動的檔案
- `ContentView.swift` — tab 結構差異是功能門控
- `BooksBrowserApp.swift` — iOS-only service 注入
- `Views/Reader/*`（除 Headers）— 整檔 iOS-only，internal sizeClass 判斷保持

## 風險

| 風險 | 緩解 |
|------|------|
| iPad side panel 與 NavigationStack push 動畫衝突 | macOS 已驗證此模式可行，iPad 行為一致 |
| iPad split-screen 時從 regular 變 compact，detail panel 需平滑消失 | `animation(AppMotion.standardSpring, value: layoutMode)` + 在 layoutMode 切換時自動 dismiss detail |
| `VocabularyListSheets` 移除 sizeClass 參數是否有隱含依賴 | 檢查：目前 modifier body 完全不讀 sizeClass，只掛 sync/settings/share sheet |
