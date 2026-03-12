# Vocabulary Feature Boundary

## 檔案清冊

### Container Layer（組裝 + 路由）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `VocabularyListView.swift` | 77 | 主容器 `struct VocabularyListView: View` |
| `VocabularyListView+State.swift` | 161 | 狀態持有 extension |
| `VocabularyListView+Toolbar.swift` | 125 | toolbar extension |
| `VocabularyListView+Sheets.swift` | 74 | sheet 槽 extension |
| `SyncView.swift` | 89 | `struct SyncView: View`，同步畫面容器 |
| `KnowledgeGraphView.swift` | 73 | `struct KnowledgeGraphView: View`，知識圖譜容器 |

### Coordinator Layer（導航協調）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `VocabularyListCoordinator.swift` | 77 | `@Observable @MainActor final class VocabularyListCoordinator` |
| `KnowledgeGraphCoordinator.swift` | 78 | `@Observable @MainActor final class KnowledgeGraphCoordinator` |
| `Scenes/KGVocabCoordinator.swift` | 111 | `@Observable @MainActor final class KGVocabCoordinator` |
| `Scenes/SyncCoordinator.swift` | 256 | `@Observable @MainActor final class SyncCoordinator`，含 `PipelineStep` / `SyncPhase` / `SyncFailureKind` |

### Presenter Layer（純 UI 呈現）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/VocabularyListPresenter.swift` | 54 | `struct VocabularyListPresenter<Content>: View` + `VocabularyListPresenterState` |
| `Scenes/PendingVocabPresenter.swift` | 94 | `struct PendingVocabPresenter: View` + `PendingVocabPresenterState` |
| `Scenes/KGVocabPresenter.swift` | 254 | KG 詞彙列表佈局 |
| `Scenes/KnowledgeGraphPresenter.swift` | 255 | 知識圖譜佈局 |
| `Scenes/WordDetailPresenter.swift` | 141 | `struct WordDetailPresenter: View` |
| `Scenes/SyncPresenter.swift` | 140 | 同步主佈局 |
| `Scenes/SyncPresenter+Header.swift` | 94 | 同步 header |
| `Scenes/SyncPresenter+ActionArea.swift` | 86 | 同步 action 區域 |
| `Scenes/SyncPresenter+Preview.swift` | 279 | 同步 preview 資料 |
| `Scenes/StatsPresenter.swift` | 225 | 統計畫面佈局 |
| `Scenes/ReviewCalendarPresenter.swift` | 229 | 複習日曆佈局 |
| `Scenes/TodayReviewPresenter.swift` | 221 | 今日複習主佈局 |
| `Scenes/TodayReviewPresenter+CardContent.swift` | 251 | 卡片內容 extension |
| `Scenes/TodayReviewPresenter+Toolbar.swift` | 224 | toolbar extension |

### State Layer（狀態定義）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/TodayReviewState.swift` | 292 | `@Observable @MainActor final class TodayReviewState`，複習狀態機 |
| `Presentation/ReviewSessionStore.swift` | 35 | `struct ReviewSessionStore`，複習 session 快照 |

### Presentation Models（UI 資料轉換）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Presentation/VocabularyEntryPresentation.swift` | 143 | `enum VocabularyEntryPresentation`，詞條 UI 模型 |
| `Presentation/WordRowPresentation.swift` | 188 | 詞列行 UI 模型 |
| `Presentation/WordDetailPresentation.swift` | 130 | `enum WordDetailPresentation`，詞條詳情 UI 模型 |
| `Presentation/CardPresentation.swift` | 118 | `struct CardPresentation` + `CardLinkGroupPresentation` |
| `Presentation/KnowledgeGraphPresentation.swift` | 147 | `KnowledgeGraphNode` / `KnowledgeGraphEdge` / `KnowledgeGraphTheme` / `enum KnowledgeGraphPresentation` |
| `Presentation/StatsPresentation.swift` | 85 | `enum StatsPresentation` |
| `Presentation/KGVocabSortOption.swift` | 28 | `enum KGVocabSortOption` |

### Scenes（獨立場景 View）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/KGVocabView.swift` | 297 | `struct KGVocabView: View`，KG 詞彙列表場景 |
| `Scenes/TodayReviewView.swift` | 73 | `struct TodayReviewView: View` + `TodayReviewSession` + `TodayReviewRevealStage` |
| `Scenes/TodayReviewSwipeDeck.swift` | 114 | swipe deck 互動元件 |
| `Scenes/TodayReviewPreviewData.swift` | 197 | preview 資料 |
| `Scenes/ReviewFoldSurface.swift` | 119 | `struct ReviewFoldSurface` + `ReviewFoldChevronButton/Pill` |
| `Scenes/WordDetailSheet.swift` | 56 | `struct WordDetailSheet: View` |
| `Scenes/WordEditSheet.swift` | 67 | `struct WordEditSheet: View` |
| `Scenes/ArchivedVocabSheet.swift` | 99 | `struct ArchivedVocabSheet: View` |
| `GraphWebView.swift` | 224 | `struct GraphWebView: UIViewRepresentable` + `GraphForces` |

### Components（可復用 UI 元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Components/VocabShellComponents.swift` | 587 | shell 級元件庫：`VocabTabSelector` / `VocabChromePill` / `VocabSearchField` / `VocabListCard` 等 |
| `Components/VocabSkinComponents.swift` | 211 | skin 級元件：`VocabCard` / `VocabToneChip` / `VocabEmptyStateCard` / `VocabReviewProgressBar` 等 |
| `Components/WordRow.swift` | 159 | `struct WordRow: View` |
| `Components/VocabSwipeRow.swift` | 105 | `struct VocabSwipeRow<Content>: View` |
| `Components/CardDocumentView.swift` | 327 | card document 主 View |
| `Components/CardRichTextRenderer.swift` | 277 | rich text renderer |
| `Components/CardSections.swift` | 280 | card 各 section 元件 |
| `Components/CardDocumentBuilder.swift` | 89 | `CardDocument` builder |
| `Components/CardDocumentModels.swift` | 92 | `CardDocument` / `CardDocumentBlock` 等 data model |
| `Components/CardMarkdownInlineParser.swift` | 118 | Markdown inline 解析器 |
| `Components/WordDetailComponents.swift` | 99 | 詞條詳情子元件 |
| `Components/VocabCalendarGrid.swift` | 149 | 日曆格元件 |
| `Components/VocabActivityHeatmap.swift` | 154 | 活躍熱圖元件 |
| `Components/VocabForecastChart.swift` | 62 | 預測圖表元件 |

### Overlay Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Overlay/LinkedCardOverlayStack.swift` | 83 | `struct LinkedCardOverlayStack: View`，關聯卡片 overlay |

### Skin Layer（Design Token）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Skin/VocabSkin.swift` | 601 | `struct VocabSkin`，Vocabulary feature 專屬 design system token |

---

## 改動規則

- **新增列表 UI** → `Scenes/VocabularyListPresenter.swift` 或新增 Presenter extension
- **新增業務流程** → Coordinator（`VocabularyListCoordinator` / `SyncCoordinator` / `KGVocabCoordinator`）
- **新增 UI 資料模型** → `Presentation/` 下新增或擴充現有 Presentation enum/struct
- **新增可復用元件** → `Components/VocabShellComponents.swift`（shell 級）或 `VocabSkinComponents.swift`（skin 級）
- **新增場景** → `Scenes/` 新增 View + Presenter + Coordinator，並在對應 container 的 Sheets extension 掛載
- **新增 design token** → `Skin/VocabSkin.swift`（禁止在 feature 檔案裡硬編碼顏色/間距）

## State 邊界

- `TodayReviewState`：複習 session 狀態機，僅 `TodayReviewView` 持有，不外洩
- `SyncCoordinator`：同步流程狀態，僅 `SyncView` 持有
- `KGVocabCoordinator`：KG 詞彙列表狀態，僅 `KGVocabView` 持有
- `VocabularyListCoordinator`：詞彙列表主導航狀態，由 `VocabularyListView` 持有
- Presentation models（`Presentation/`）：純值類型，可跨 layer 傳遞，但不持有 mutable state

## 共用依賴

| Token | 用途 |
|-------|------|
| `VocabSkin` | Vocabulary 專屬 design token，`@Environment(\.vocabSkin)` |
| `AppTheme` | 全局色彩，`@Environment(\.appTheme)` |
| `AppMetrics` / `AppShellMetrics` | 間距、尺寸 |
| `AppMotion` | 動畫 token |
| `AppTransition` | 過渡動畫 |
| `AppFonts` / `VocabSkin.Typography` | 字型 |
