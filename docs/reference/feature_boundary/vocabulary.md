<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Vocabulary/
verified_against: 8aaece8d
-->
# Vocabulary Feature Boundary

> Notebook 是本 feature 的子場景,獨立 boundary 見 `docs/reference/feature_boundary/notebook.md`(`Scenes/Notebook*` + `Components/Notebook*`)。

## 檔案清冊

### Container Layer（組裝 + 路由）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `VocabularyListView.swift` | 105 | 主容器 `struct VocabularyListView: View` |
| `VocabularyListView+State.swift` | 79 | 狀態持有 extension |
| `VocabularyListView+Toolbar.swift` | 59 | toolbar extension |
| `VocabularyListView+Sheets.swift` | 28 | sheet 槽 extension |
| `SyncView.swift` | 149 | `struct SyncView: View`，同步畫面容器 |
| `KnowledgeGraphView.swift` | 109 | `struct KnowledgeGraphView: View`，知識圖譜容器；graph ratio 使用 review pause reference date |

### Coordinator Layer（導航協調）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `VocabularyListCoordinator.swift` | 59 | `@Observable @MainActor final class VocabularyListCoordinator` |
| `KnowledgeGraphCoordinator.swift` | 80 | `@Observable @MainActor final class KnowledgeGraphCoordinator` |
| `Scenes/KGVocabCoordinator.swift` | 204 | `@Observable @MainActor final class KGVocabCoordinator`，batch delete / archive 收斂集中於 coordinator；archive 的本地可收斂集合為 `updated_words ∪ not_found`，`failed` 才保留重試 |
| `Scenes/SyncCoordinator.swift` | 506 | `@Observable @MainActor final class SyncCoordinator`，含 `PipelineStep` / `SyncPhase` / `SyncFailureKind` |

### Presenter Layer（純 UI 呈現）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/VocabularyListPresenter.swift` | 66 | `struct VocabularyListPresenter<Content>: View` + `VocabularyListPresenterState` |
| `Scenes/PendingVocabPresenter.swift` | 106 | `struct PendingVocabPresenter: View` + `PendingVocabPresenterState` |
| `Scenes/KGVocabPresenter.swift` | 345 | KG 詞彙列表佈局；`KGVocabRowSelection` 控制 row detail highlight，selection mode 期間 suppress highlight，避免 detail selection 與 batch selection 混淆；row review progress 使用 review pause reference date |
| `Scenes/KnowledgeGraphPresenter.swift` | 357 | 知識圖譜佈局 |
| `Scenes/WordDetailPresenter.swift` | 274 | `struct WordDetailPresenter: View`；`WordDetailInspectorMetrics` 將右側 inspector 內容限寬 320–640pt，metadata footer 走 `CollocationFlowLayout` capsule flow，避免桌面窄欄 HStack 擠爆 |
| `Scenes/SyncPresenter.swift` | 228 | 同步主佈局 |
| `Scenes/SyncPresenter+Header.swift` | 95 | 同步 header |
| `Scenes/SyncPresenter+ActionArea.swift` | 86 | 同步 action 區域 |
| `Scenes/SyncPresenter+Preview.swift` | 290 | 同步 preview 資料 |
| `Scenes/StatsPresenter.swift` | 520 | 統計畫面佈局；forecast 與 graph thumbnail 使用 review pause reference date |
| `Scenes/ReviewCalendarPresenter.swift` | 255 | 複習日曆佈局 |
| `Scenes/TodayReviewPresenter.swift` | 336 | 今日複習主佈局；翻卡路徑含 `PerfLog` render/layout tick，autoplay 答案揭露後朗讀 |
| `Scenes/TodayReviewPresenter+CardContent.swift` | 293 | 卡片內容 extension；翻卡 front/back surface 與 radius 計算含 `PerfLog` instrumentation |
| `Scenes/TodayReviewPresenter+Toolbar.swift` | 457 | toolbar extension；autoplay controls 含聲音開關 |

### State Layer（狀態定義）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/TodayReviewState.swift` | 551 | `@Observable @MainActor final class TodayReviewState`，複習場景 owner；持有 scoring / persistence / analytics / cache orchestration，queue+reveal 導航委派 `TodayReviewSessionState` |
| `Scenes/TodayReviewSessionState.swift` | 64 | `struct TodayReviewSessionState<Entry>`，純 session/navigation domain state；封裝 queue / currentIndex / revealStage / shuffle / next / previous / completion 判定 |
| `Presentation/ReviewSessionStore.swift` | 117 | `struct ReviewSessionStore`，複習 session order 持久化；使用 `kg:<cardId>` / `local:<uuid>` persistence id、user scope 與 queue fingerprint |

### Presentation Models（UI 資料轉換）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Presentation/VocabularyEntryPresentation.swift` | 211 | `enum VocabularyEntryPresentation`，詞條 UI 模型 |
| `Presentation/WordRowPresentation.swift` | 138 | 詞列行 UI 模型；review state/relative label/progress 支援注入 `now` |
| `Presentation/WordDetailPresentation.swift` | 122 | `enum WordDetailPresentation`，詞條詳情 UI 模型 |
| `Presentation/CardPresentation.swift` | 148 | `struct CardPresentation` + `CardLinkGroupPresentation` |
| `Presentation/KnowledgeGraphPresentation.swift` | 183 | `KnowledgeGraphNode` / `KnowledgeGraphEdge` / `KnowledgeGraphTheme` / `enum KnowledgeGraphPresentation` |
| `Presentation/StatsPresentation.swift` | 99 | `enum StatsPresentation`；`buildSummary(..., now:)` 支援 frozen review clock |
| `Presentation/KGVocabSortOption.swift` | 28 | `enum KGVocabSortOption` |

### Scenes（獨立場景 View）

> Notebook 場景(`Scenes/NotebookListView.swift` / `NotebookListCoordinator.swift` / `NotebookEditSheet.swift`)獨立 boundary 見 `docs/reference/feature_boundary/notebook.md`,本表不重列。

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/KGVocabView.swift` | 348 | `struct KGVocabView: View`，KG 詞彙列表場景；持有 `selectedRowID` 以在 desktop 三欄工作流中保留「目前右側 detail 對應哪一列」的中欄視覺狀態，filtered rows 移除該 id 時自動清空。整頁 error state 與離線 banner 都用固定重試文案，避免把低階 error message 直接暴露到 UI；分類/sort 使用 review pause reference date |
| `Scenes/TodayReviewView.swift` | 493 | `struct TodayReviewView: View` + `TodayReviewSession` + `TodayReviewRevealStage` |
| `Scenes/TodayReviewPhaseView.swift` | 176 | `struct TodayReviewPhaseView: View`，複習階段切換場景 |
| `Scenes/TodayReviewSwipeDeck.swift` | 127 | swipe deck 互動元件 |
| `Scenes/TodayReviewPreviewData.swift` | 253 | preview 資料 |
| `Scenes/TodayReviewMetrics.swift` | 103 | TodayReview feature-local 版面 metrics(`static let`,~44 個) |
| `Scenes/TodayReviewSessionSnapshotStore.swift` | 122 | `TodayReviewState` session snapshot 持久化 |
| `Scenes/ReviewFoldSurface.swift` | 108 | `struct ReviewFoldSurface` + `ReviewFoldChevronPill` |
| `Scenes/ReviewScoringState.swift` | 56 | 複習評分子狀態 |
| `Scenes/ReviewSessionPersistence.swift` | 271 | 複習 session 落地/恢復邏輯 |
| `Scenes/SelectionModeState.swift` | 47 | 列表多選模式狀態 |
| `Scenes/OverviewTab.swift` | 64 | `struct OverviewTab: View`，Vocab 入口 overview tab |
| `Scenes/AddLinkSheet.swift` | 121 | `struct AddLinkSheet: View`，KG 手動加連線 sheet |
| `Scenes/WordDetailSheet.swift` | 251 | `struct WordDetailSheet: View` |
| `Scenes/WordEditSheet.swift` | 105 | `struct WordEditSheet: View` |
| `Scenes/ArchivedVocabSheet.swift` | 118 | `struct ArchivedVocabSheet: View` |
| `GraphWebView.swift` | 281 | `struct GraphWebView: UIViewRepresentable` + `GraphForces` |
| `GraphThumbnailWebView.swift` | 165 | `GraphThumbnailHolder` + `GraphThumbnailCoordinator` + `GraphThumbnailWebView`，跨 tab 切換存活的圖譜縮圖 WKWebView（不可互動、載入同 `graph.html`） |
| `AutoSyncMonitor.swift` | 100 | `struct AutoSyncMonitor: ViewModifier`，監看 `pendingEntries`、auto-sync toggle、網路離線→連線恢復事件並 debounce 觸發 auto-sync（`minTriggerInterval` 防 hot loop） |

### Components（可復用 UI 元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Components/VocabShellComponents.swift` | 205 | shell 級元件庫：`VocabTabSelector` / `VocabChromePill` / `VocabSearchField` 等 |
| `Components/VocabShellComponents+Lists.swift` | 234 | shell 級 list cards / status hero / timeline / button styles(`VocabListCard` 等) |
| `Components/VocabShellComponents+Actions.swift` | 248 | `VocabSortPill` + `VocabReviewCTAPill`(brandHero 填色 capsule，與 sort pill 同列尾端，由 `KGVocabPresenter.State.ReviewCTA` 驅動) |
| `Components/VocabComponents.swift` | 277 | skin 級元件:`VocabCard` / `VocabToneChip` / `VocabEmptyStateCard` / `VocabReviewProgressBar` 等(前身 `VocabSkinComponents.swift`,隨 AppSkin 正名整併) |
| `Components/VocabSceneShell.swift` | 157 | `VocabSceneShell<Content>` + `VocabScenePhase`,統一 vocabulary 四態容器(loading / loadingSkeleton / empty / error / content)；error phase 可帶 description，retry action 維持 owner 注入 |
| `Components/WordRow.swift` | 254 | `struct WordRow: View`（Phase 2 起 lineLimit + truncationMode + fixedSize + monospacedDigit 套到 word/pos/translation/book/trailing/status；原專屬 stress baseline 隨 Notebook Detail catalog surface 於 catalog scope campaign 1b 一併 CUT，尚無替代具名 surface，視需要列入後續 MISSING 補拍） |
| `Components/VocabReviewBanner.swift` | 159 | `struct VocabReviewBanner<FilterContent>: View`。完整 hero CTA(cardBackground + title + stats + button)，**僅** NotebookListView 使用作為 primary entry point。VocabularyListView 詳情頁不再渲染此 banner — CTA 改走 `VocabReviewCTAPill` 內嵌於 chip+sort 列。 |
| `Components/CardDocumentView.swift` | 486 | card document 主 View；重型 card document render path 含 `PerfLog` tick |
| `Components/CardRichTextRenderer.swift` | 418 | rich text renderer；render path 含 `PerfLog` tick |
| `Components/CardSections.swift` | 298 | card 各 section 元件 |
| `Components/CardDocumentBuilder.swift` | 92 | `CardDocument` builder |
| `Components/CardDocumentModels.swift` | 178 | `CardDocument` / `CardDocumentBlock` 等 data model |
| `Components/CardMarkdownInlineParser.swift` | 118 | Markdown inline 解析器 |
| `Components/WordDetailComponents.swift` | 181 | 詞條詳情子元件 |
| `Components/CollocationExplainSheet.swift` | 122 | `struct CollocationExplainSheet: View`，搭配詞翻譯 sheet（借用 `ReaderMetrics` 對齊 Reader panel，見共用依賴） |
| `Components/VocabCalendarGrid.swift` | 182 | 日曆格元件 |
| `Components/VocabActivityHeatmap.swift` | 184 | 活躍熱圖元件 |
| `Components/VocabForecastChart.swift` | 167 | 預測圖表元件 |
| `Components/BookshelfItem.swift` | 26 | `enum BookshelfItem` / `BookshelfDestination`，書架統一條目（notebook / podcastSeries 二態 + 排序 key） |
| `Components/ProgressCapsule.swift` | 44 | `struct ProgressCapsule: View`，通用進度 capsule（fill / track / label） |
| `Components/SelectionToolbar.swift` | 63 | `struct SelectionToolbar: View`，多選模式底部封存／刪除工具列 |
| `Components/PressableInteraction.swift` | 37 | `PressableStyle` / `LiftableButtonStyle` ButtonStyle（按壓縮放/抬升回饋 + `.pressable` / `.liftable` 便捷取用） |

### Overlay Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Overlay/LinkedCardOverlayStack.swift` | 82 | `struct LinkedCardOverlayStack: View`，關聯卡片 overlay |
| `Overlay/LinkReasonSheet.swift` | 73 | `struct LinkReasonSheet: View`，KG 連結理由 sheet（顯示 `KGCardLinkSummary`，提供導航/隱藏 link 動作） |

> Design token 已從 feature 本地 `Skin/VocabSkin.swift` 升格為全 app 共用 `AppSkin`(見 `ios/BooksBrowser/Models/AppSkin.swift`),不再屬於 Vocabulary feature scope。

---

## 改動規則

- **新增列表 UI** → `Scenes/VocabularyListPresenter.swift` 或新增 Presenter extension
- **新增業務流程** → Coordinator（`VocabularyListCoordinator` / `SyncCoordinator` / `KGVocabCoordinator`）
- **新增 UI 資料模型** → `Presentation/` 下新增或擴充現有 Presentation enum/struct
- **新增可復用元件** → `Components/VocabShellComponents*.swift`（shell 級）或 `Components/VocabComponents.swift`（skin 級）
- **新增場景** → `Scenes/` 新增 View + Presenter + Coordinator，並在對應 container 的 Sheets extension 掛載
- **新增 design token** → `ios/BooksBrowser/Models/AppSkin.swift`（全 app 共用；禁止在 feature 檔案裡硬編碼顏色/間距）

## State 邊界

- `TodayReviewState`：複習 scene owner，負責 orchestration；僅 `TodayReviewView` 持有，不外洩
- `TodayReviewSessionState`：純 session/navigation state，僅 `TodayReviewState` 持有
- `SyncCoordinator`：同步流程狀態，僅 `SyncView` 持有
- `KGVocabCoordinator`：KG 詞彙列表狀態，僅 `KGVocabView` 持有
- `VocabularyListCoordinator`：詞彙列表主導航狀態，由 `VocabularyListView` 持有
- Presentation models（`Presentation/`）：純值類型，可跨 layer 傳遞，但不持有 mutable state

## 共用依賴

| Token | 用途 |
|-------|------|
| `AppSkin` | 全 app 共用 feature-level UI token(前身 `VocabSkin`,已正名),`@Environment(\.appSkin)` |
| `AppTheme` | 全局色彩，`@Environment(\.appTheme)` |
| `AppMetrics` / `AppShellMetrics` | 間距、尺寸 |
| `AppMotion` | 動畫 token |
| `AppTransition` | 過渡動畫 |
| `AppFonts` / `AppSkin.Typography` | 字型 |
| `TodayReviewMetrics` | TodayReview feature-local 版面參數（card / topBar / toolbar / fold / swipe geometry 等，~44 個 static let，定義於 `Scenes/TodayReviewMetrics.swift`）。boundary rectify 2026-05 從 `AppSkin.Metrics`/`Spacing` 遷出 24 個欄位 |
| `ReaderMetrics`（**跨 feature 借用**） | `Components/CollocationExplainSheet.swift` 使用 `ReaderMetrics.panelHorizontalInset` / `.panelBottomInset`，目的是讓翻譯 sheet 視覺對齊 Reader panel。**未來 Reader 重構時 Vocabulary 是 stakeholder** |
