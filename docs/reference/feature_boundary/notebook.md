<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListCoordinator.swift
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookEditSheet.swift
  - ios/BooksBrowser/Views/Vocabulary/Components/Notebook*.swift
verified_against: f63ace78
-->
# Notebook Feature Boundary

> Notebook 是 Vocabulary feature 的子場景(不獨立成 `Views/Notebook/` 目錄,
> 檔案分散於 `Views/Vocabulary/Scenes/` 與 `Views/Vocabulary/Components/`)。
> 與 `Views/Vocabulary/` 的整體 scope 邊界一起讀:`docs/reference/feature_boundary/vocabulary.md`。

## 檔案清冊

### Scenes Layer（容器 / 主場景）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/NotebookListView.swift` | 620 | 主場景 `struct NotebookListView: View`。**Adaptive layout (Phase 4a)**：`notebooks.count == 1` → 單一 `NotebookCard(style: .hero)` 跨整列寬；`≥2` → `LazyVGrid` 純 notebook 卡(D5: inline `NotebookAddCard` 已移除)。**D4 editorial banner**: 頂部 `今日複習` page section header + `VocabReviewCTAPill`(無卡片框,同詳情頁視覺族群),取代舊 `VocabReviewBanner`。**D6 filter**: `NotebookFilterChip` 從 banner 移入 toolbar 變 `line.3.horizontal.decrease.circle` button → `NotebookFilterPickerSheet`,只在 `notebooks.count >= 2` 顯示。**D7 toolbar**: `[filter?] [sort] [archive] [+]`。`+` 唯一在 toolbar。 |
| `Scenes/NotebookListCoordinator.swift` | 282 | `@Observable @MainActor final class NotebookListCoordinator`，導航 + sheet 狀態 + cover photo 編輯流程（含 `photoError` + `originalCoverImagePath` 延遲刪 + 取消還原） |
| `Scenes/NotebookEditSheet.swift` | 279 | `struct NotebookEditSheet: View`，建立/編輯 notebook sheet（含 cover system 選色/選 pattern/匯入照片） |

### Components Layer（可復用元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Components/NotebookCard.swift` | 415 | `struct NotebookCard: View` + `enum NotebookCardStyle { .grid, .hero }`。**D1 cover composition**: 含私有 `EditorialCoverComposition` 以 `.overlay` 套在既有 cover view 上 — serif `AppFonts.serif(size: 22/32, bold: true)` name 左上 + `GeometryReader` 動態 hairline rule(寬 cover×0.25,色 `NotebookPalette.darken(cover, by: 0.3)`)+ `L10n.format("%@ 詞")` monoLabel 右下(cardCount > 0 才顯示)+ **D3** 3pt spine(grid + active,色 `NotebookPalette.darken(cover, by: 0.4)`)。**D2 bottom**: ProgressCapsule (fillColor=coverColor,editorial 同色族) + 條件 due chip(invisible placeholder 撐高保 grid 同高)。**Dark mode**: `coverColor` 自動套 `NotebookPalette.darken(_, by: 0.2)` 配 contrast test。Hero 21:10、無 spine。`NotebookAddCard` 同 aspect 對齊保留(future onboarding 用,**NotebookListView 不再 inline**)。 |
| `Components/NotebookStackedCoverView.swift` | ~155 | Editorial 立體堆卡。**新增 `showsName: Bool = true` 透傳至內層 `NotebookCoverView`** — NotebookCard 套 editorial overlay 時傳 false 避免雙層 name。其餘維持:彩色封面 + cream 紙頁三階 ghost,deterministic rotation + dx jitter,`NotebookDeckButtonStyle` press env。 |
| `Components/NotebookStackMetrics.swift` | ~105 | 立體堆卡 token 集中地。**新增 `patternOpacity: Double = 0.12`** — `NotebookCoverPatterns` 6 種 pattern 統一引此 token(noise 例外,保動態公式)。其餘維持 `layerCount` / offsets / rotations / `stableSeed` / `ghostPaperColor`。 |
| `Components/NotebookCoverPatterns.swift` | ~200 | 6 種 SwiftUI Canvas pattern 渲染(dots / lines / grid / waves / circles / noise)+ `NotebookCoverView`(頂層封面實體 view)。**新增 `showsName: Bool = true`** — gate 中央白字 name 渲染。5 處非 NotebookCard callsite(Bookshelf / Podcast / EditSheet / StackedCoverView / #Preview)default true zero-touch。pattern stroke/fill opacity 統一引 `NotebookStackMetrics.patternOpacity`。 |
| `Components/NotebookPalette.swift` | ~55 | 12 色 Morandi 色票 + `color(for:)` + **新增 `darken(_:by:)` HSB helper**(brightness ×(1-amount),hue/sat 保留;cover hairline rule / D3 spine / dark mode cover 用)。 |
| `Components/NotebookFilterChip.swift` | 123 | filter chip：全部 / 有待複習 / 已學完 / 自訂排序 |

---

## 改動規則

- **新增 notebook list UI** → `NotebookListView`，狀態組裝抽到 `NotebookListCoordinator`
- **新增 notebook card 樣式** → `NotebookCard`(cover overlay `EditorialCoverComposition` / ProgressCapsule + 條件 due chip);新增 cover pattern 走 `NotebookCoverPatterns` + 在 enum 加 case + opacity 引 `NotebookStackMetrics.patternOpacity`
- **新增 cover 配色** → `NotebookPalette` 加 case；保持 12 色限制（UI 一致性）
- **新增建立/編輯欄位** → `NotebookEditSheet` 表單；驗證邏輯走 coordinator
- **新增 notebook 操作（archive / share / export）** → `NotebookCardActions` context menu + `NotebookListCoordinator` 加 action handler
- **新增 filter / sort** → `NotebookFilterChip` 擴 enum；資料層走 SwiftData `@Query` predicate
- **改動 notebook 與卡片的綁定關係** → 涉及 `resolveNotebookId` chokepoint / `sanitizeOutbox` / `triggerPipelinesIsolated`，動之前讀 `docs/sop/architecture.md` §Notebook 同步 + `docs/reference/sync_lifecycle.md`

## State 邊界

- `NotebookListCoordinator`：notebook 列表的導航、sheet、cover photo 編輯狀態（含取消還原機制），由 `NotebookListView` 持有
- Notebook 資料模型來自 SwiftData，**不**放 coordinator
- `NotebookEditSheet` 的編輯草稿狀態為 sheet-local，submit 才走 coordinator 持久化
- Notebook ID 解析必經 `resolveNotebookId` 單一入口（防 orphan）

## 共用依賴

| Token | 用途 |
|-------|------|
| `VocabSkin` | 共用詞彙 feature design token（cover / banner 顏色） |
| `AppTheme` | 色彩，`@Environment(\.appTheme)` |
| `AppMetrics` / `AppShellMetrics` | 間距、尺寸 |
| `AppMotion` | 動畫 token |
| `NotebookPalette` | 12 色封面色票 |

## 相關 doc

- `docs/reference/feature_boundary/vocabulary.md` — 母 feature 的整體 scope（含 KGVocab / TodayReview / Sync）
- `docs/reference/sync_lifecycle.md` **(SoT)** — notebook ↔ 卡片 sync 狀態流轉
- `docs/sop/architecture.md` §Notebook robustness — `resolveNotebookId` / `sanitizeOutbox` / `triggerPipelinesIsolated` 防禦設計
- `docs/reference/product_surface.md` §Notebook bookshelf — 已實作功能清冊
