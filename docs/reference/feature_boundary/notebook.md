<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListCoordinator.swift
  - ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookEditSheet.swift
  - ios/BooksBrowser/Views/Vocabulary/Components/Notebook*.swift
verified_against: 1d2a399
-->
# Notebook Feature Boundary

> Notebook 是 Vocabulary feature 的子場景(不獨立成 `Views/Notebook/` 目錄,
> 檔案分散於 `Views/Vocabulary/Scenes/` 與 `Views/Vocabulary/Components/`)。
> 與 `Views/Vocabulary/` 的整體 scope 邊界一起讀:`docs/reference/feature_boundary/vocabulary.md`。

## 檔案清冊

### Scenes Layer（容器 / 主場景）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/NotebookListView.swift` | 601 | 主場景 `struct NotebookListView: View`。**Adaptive layout (Phase 4a)**：`notebooks.count == 1` → 單一 `NotebookCard(style: .hero)` 跨整列寬；`≥2` → `LazyVGrid` + `NotebookAddCard`。`VocabReviewBanner` 在單 notebook 時不掛 `NotebookFilterChip`(scope filter 無意義)。`+` 永遠在 toolbar。 |
| `Scenes/NotebookListCoordinator.swift` | 282 | `@Observable @MainActor final class NotebookListCoordinator`，導航 + sheet 狀態 + cover photo 編輯流程（含 `photoError` + `originalCoverImagePath` 延遲刪 + 取消還原） |
| `Scenes/NotebookEditSheet.swift` | 279 | `struct NotebookEditSheet: View`，建立/編輯 notebook sheet（含 cover system 選色/選 pattern/匯入照片） |

### Components Layer（可復用元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Components/NotebookCard.swift` | 326 | `struct NotebookCard: View` + `enum NotebookCardStyle { .grid, .hero }`。Grid 套 `NotebookStackedCoverView` 立體堆卡 + 整卡 `LayoutMode.notebookCardAspectRatio` (3:4) + stable-height metadata（ProgressCapsule / chips row 永遠 render）。Hero 維持 21:10 平面 cover、隱藏使用中 pill。`NotebookAddCard` 同 aspect 對齊。Press-in 由 `NotebookDeckButtonStyle` 承載（NotebookListView 套）。 |
| `Components/NotebookStackedCoverView.swift` | ~150 | Editorial 立體堆卡：彩色封面 + cream 紙頁三階 ghost（`AppColors.paperLight/paperSepia/paperSepiaDeep`）。`ZStack` 由下而上 render `layerCount` 層；每層套 deterministic 微 rotation + dx jitter（per-notebook `stableSeed`，anchor `.bottom`）+ 0.5pt `cardBorder` hairline。內含 `IsDeckPressedKey` / `DeckReduceMotionKey` env + `NotebookDeckButtonStyle`。下層 ghost `.appElevation(.z1)`、頂層 `.z2`。Top cover rotation 由 `NotebookCard.coverArea` 在外層套（包 pill overlay 一起轉）。 |
| `Components/NotebookStackMetrics.swift` | ~95 | 立體堆卡 token 集中地：`layerCount(forCardCount:)` (0→1 / 1-50→2 / 51-200→3 / 200+→4)、`layerOffsetY` / `layerInsetX` (4pt) / `pressedTopOffsetY` (-14) / `layerRotations` ±1.5° base / `layerDxJitter` ±1pt / `rotationOverhang` (8pt)、`seedJitter(seed:depth:)` deterministic perturb、`stableSeed(for:)` djb2 cross-launch hash（取代 `String.hashValue`）、`ghostPaperColor(depth:scheme:)` cream paper 三階。**已移除**：brightness-based `deckColor` / `brightnessStepLight/Dark` / `Color.shiftingBrightness`（editorial stack 改 cream paper ghost）。 |
| `Components/NotebookCoverPatterns.swift` | 198 | 6 種 SwiftUI Canvas pattern 渲染（dots / lines / waves / 等）+ `NotebookCoverView`（頂層封面實體 view）|
| `Components/NotebookPalette.swift` | 34 | 12 色色票 enum + 對應 `Color`（cover 配色系統） |
| `Components/NotebookFilterChip.swift` | 123 | filter chip：全部 / 有待複習 / 已學完 / 自訂排序 |

---

## 改動規則

- **新增 notebook list UI** → `NotebookListView`，狀態組裝抽到 `NotebookListCoordinator`
- **新增 notebook card 樣式** → `NotebookCard`（cover / progress / banner 三層）；新增 cover pattern 走 `NotebookCoverPatterns` + 在 enum 加 case
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
