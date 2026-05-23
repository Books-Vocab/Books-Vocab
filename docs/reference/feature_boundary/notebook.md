<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListCoordinator.swift
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookEditSheet.swift
  - ios/BooksBrowser/Views/Vocabulary/Components/Notebook*.swift
verified_against: c02b5221
-->
# Notebook Feature Boundary

> Notebook 是 Vocabulary feature 的子場景(不獨立成 `Views/Notebook/` 目錄,
> 檔案分散於 `Views/Vocabulary/Scenes/` 與 `Views/Vocabulary/Components/`)。
> 與 `Views/Vocabulary/` 的整體 scope 邊界一起讀:`docs/reference/feature_boundary/vocabulary.md`。

## 檔案清冊

### Scenes Layer（容器 / 主場景）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/NotebookListView.swift` | ~600 | 主場景 `struct NotebookListView: View`。**Unified LazyVStack book-row layout** — 所有 notebook 一律 full-width row(取消 hero/grid 分支)。**Inline pill cluster**(取代舊 banner + toolbar buttons):`今日複習` page section header + `VocabReviewCTAPill` + filter pill(`notebooks.count >= 2` 才顯示,觸發 `NotebookFilterPickerSheet`) + 新增 pill,全部在 ScrollView 內。Pill cluster 與 notebook list 間用 `AppAirDivider`(hairline + 32pt margin)分區,不再用整盒 border 切割(Mochi 北極星二)。**Toolbar 只剩** `[sort] [archive]`。 |
| `Scenes/NotebookListCoordinator.swift` | 282 | `@Observable @MainActor final class NotebookListCoordinator`，導航 + sheet 狀態 + cover photo 編輯流程（含 `photoError` + `originalCoverImagePath` 延遲刪 + 取消還原） |
| `Scenes/NotebookEditSheet.swift` | 279 | `struct NotebookEditSheet: View`，建立/編輯 notebook sheet（含 cover system 選色/選 pattern/匯入照片） |

### Components Layer（可復用元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Components/NotebookCard.swift` | ~440 | `struct NotebookCard: View` — **HStack book-row,固定 72pt 高**(取代舊 VStack `EditorialCoverComposition` overlay 設計)。**Mochi Phase 3:整卡外框 stroke 已移除**(北極星二 border 退場),靠 `cardBackground` vs `pageBackground` 色差 + 卡片間留白分區。Cover 40% 寬左欄:`coverColor` 底 + 統一 noise pattern (opacity 0.04) + 可選 `NotebookCoverPattern` 疊層 + serif italic name `AppFonts.serif(size: 17, bold: true).italic()` 左上 + active 5pt 圓點(`NotebookPalette.darken(cover, by: 0.5)`,取代舊 3pt spine / 「使用中」pill)+ 1pt editorial rule(寬 cover×0.3,同 darken 0.5)。0.5pt 垂直 `cardBorder` rule 切隔(書背隱喻內部結構,保留)。Metadata 右欄:`N 詞` monoLabel + (dueCount > 0) 5pt warning 圓點 + count + `ProgressCapsule`(4pt, fillColor=coverColor);`cardCount == 0` 顯示「尚未加入單字」placeholder。**Dark mode**: `coverColor` 自動套 `NotebookPalette.darken(_, by: 0.2)`(contrast test 鎖)。Hero style + `EditorialCoverComposition` + `coverArea` / `metadataArea` / `NotebookAddCard` 為 dead code,待清。 |
| `Components/NotebookStackedCoverView.swift` | ~155 | Editorial 立體堆卡。**新增 `showsName: Bool = true` 透傳至內層 `NotebookCoverView`** — NotebookCard 套 editorial overlay 時傳 false 避免雙層 name。其餘維持:彩色封面 + cream 紙頁三階 ghost,deterministic rotation + dx jitter,`NotebookDeckButtonStyle` press env。 |
| `Components/NotebookStackMetrics.swift` | ~105 | 立體堆卡 token 集中地。**新增 `patternOpacity: Double = 0.12`** — `NotebookCoverPatterns` 6 種 pattern 統一引此 token(noise 例外,保動態公式)。其餘維持 `layerCount` / offsets / rotations / `stableSeed` / `ghostPaperColor`。 |
| `Components/NotebookCoverPatterns.swift` | ~200 | 6 種 SwiftUI Canvas pattern 渲染(dots / lines / grid / waves / circles / noise)+ `NotebookCoverView`(頂層封面實體 view)。**新增 `showsName: Bool = true`** — gate 中央白字 name 渲染。5 處非 NotebookCard callsite(Bookshelf / Podcast / EditSheet / StackedCoverView / #Preview)default true zero-touch。pattern stroke/fill opacity 統一引 `NotebookStackMetrics.patternOpacity`。 |
| `Components/NotebookPalette.swift` | ~55 | 12 色 Morandi 色票 + `color(for:)` + **新增 `darken(_:by:)` HSB helper**(brightness ×(1-amount),hue/sat 保留;cover hairline rule / D3 spine / dark mode cover 用)。 |
| `Components/NotebookFilterChip.swift` | 123 | filter chip：全部 / 有待複習 / 已學完 / 自訂排序 |

---

## 改動規則

- **新增 notebook list UI** → `NotebookListView`，狀態組裝抽到 `NotebookListCoordinator`
- **新增 notebook card 樣式** → `NotebookCard` HStack book-row(cover 40% 左 + metadata 右);新增 cover pattern 走 `NotebookCoverPatterns` + 在 enum 加 case + opacity 引 `NotebookStackMetrics.patternOpacity`
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
