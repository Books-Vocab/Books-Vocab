<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Views/Vocabulary/
verified_against: c907585a0
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
| `Scenes/SyncCoordinator.swift` | 662 | `@Observable @MainActor final class SyncCoordinator`，含 `SyncFailureKind`；`PipelineStep` / `SyncPhase` 已移至 `Services/SyncProgress.swift`（設定頁的逐步同步進度共用同一組型別）；字典卡走**獨立 projection**（`/api/dictionary-cards`）與 vocab projection 併行收斂 |
| `Scenes/AddLinkCoordinator.swift` | 282 | `@Observable @MainActor final class AddLinkCoordinator`，Add Link 的字典區流程：搜尋 → 選義項/例句 → materialize（stable `Idempotency-Key`）→ targeted upsert，含 transport race 收斂 |

### Presenter Layer（純 UI 呈現）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/VocabularyListPresenter.swift` | 66 | `struct VocabularyListPresenter<Content>: View` + `VocabularyListPresenterState` |
| `Scenes/PendingVocabPresenter.swift` | 106 | `struct PendingVocabPresenter: View` + `PendingVocabPresenterState` |
| `Scenes/KGVocabPresenter.swift` | 345 | Books & Vocab 詞彙列表佈局；`KGVocabRowSelection` 控制 row detail highlight，selection mode 期間 suppress highlight，避免 detail selection 與 batch selection 混淆；row review progress 使用 review pause reference date |
| `Scenes/KnowledgeGraphPresenter.swift` | 357 | 知識圖譜佈局 |
| `Scenes/WordDetailPresenter.swift` | 345 | `struct WordDetailPresenter: View`；`WordDetailInspectorMetrics` 將右側 inspector 內容限寬 320–640pt，metadata footer 走 `CollocationFlowLayout` capsule flow，避免桌面窄欄 HStack 擠爆。**卡片生命週期動作依成本分層**：封存在標題列（`archivebox` ⇄ `archivebox.fill` 單擊切換，`canArchive` 對未同步卡收起——`archiveCard` 以 word+notebookId 定址伺服器，未同步必 404）；刪除壓在內容最底的 `cardManagementSection`，與卡片隔一條 `AppAirDivider`，並收編原本孤懸的「閱讀時不標記此單字」toggle |
| `Scenes/SyncPresenter.swift` | 228 | 同步主佈局 |
| `Scenes/SyncPresenter+Header.swift` | 95 | 同步 header |
| `Scenes/SyncPresenter+ActionArea.swift` | 86 | 同步 action 區域 |
| `Scenes/SyncPresenter+Preview.swift` | 290 | 同步 preview 資料 |
| `Scenes/StatsPresenter.swift` | 520 | 統計畫面佈局；forecast 與 graph thumbnail 使用 review pause reference date |
| `Scenes/ReviewCalendarPresenter.swift` | 255 | 複習日曆佈局 |
| `Scenes/TodayReviewPresenter.swift` | 425 | 今日複習主佈局；翻卡路徑含 `PerfLog` render/layout tick，autoplay 答案揭露後朗讀；由 `@Environment(\.reviewCardLayoutStore)` 讀 profile 供卡片動態排版 |
| `Scenes/TodayReviewPresenter+CardContent.swift` | 673 | 卡片內容 extension；**profile-driven 動態佈局的渲染端**——依 `ReviewCardRenderPlan` 決定各欄位出現在哪一面、把三層量測（natural / intermediate / compact）餵給 `ReviewCardLayoutSolver`、按解出的 policy 畫（例句 radius、解釋行數、搭配詞列數、知識連結 presentation、section spacing）。翻卡 front/back surface 與 radius 計算含 `PerfLog` instrumentation |
| `Scenes/TodayReviewPresenter+Toolbar.swift` | 573 | toolbar extension；autoplay controls 含聲音開關。播放鍵的可按性 = `isAutoPlaying || canAutoplay`：**守衛只擋開始、不擋停止**，否則就重造 autoplay 出不去的 bug；其 identifier 固定為 `todayReview.autoplayToggle`（a11y label 會隨播放狀態翻轉，靠 label 選取會在切換瞬間選不到）。版面編輯器入口（`rectangle.split.2x1`）與 autoplay 播放/暫停的 language-independent identifier（`todayReview.autoplay.playing|paused`）皆在此，入口與其他 chrome 共用 `isCardInteractive` 鎖 |

### State Layer（狀態定義）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/TodayReviewState.swift` | 612 | `@Observable @MainActor final class TodayReviewState`，複習場景 owner；持有 scoring / persistence / analytics / cache orchestration、review intent gating 與 collocation substate，同時把 queue+reveal 導航委派 `TodayReviewSessionState` |
| `Scenes/TodayReviewSessionState.swift` | 78 | `struct TodayReviewSessionState<Entry>`，純 session/navigation domain state；封裝 queue / currentIndex / revealStage / shuffle / next / previous / completion 判定，以及 `canAutoplay`（loop 每圈只有翻面與推進兩種動作，兩者皆不可能＝死路，播放鍵須停用而非沉默 no-op） |
| `Scenes/TodayReviewSessionPersistenceController.swift` | 73 | `struct TodayReviewSessionPersistenceController`，封裝 queue persistence metadata / snapshot / deferred flush；讓 `TodayReviewState` 不直接操作 `ReviewSessionPersistence` |
| `Scenes/TodayReviewCardCache.swift` | 98 | `struct TodayReviewCardCache`，封裝 current/next card cache、prewarm window 與 rebuild。**fling 每幀不得重建 `CardDocument` 或重走 paragraphs**——欄位資料在此預先整理好，只在 profile / 寬度 / Dynamic Type / 卡片 identity 改變時才重算（原 `PostExampleMetrics` 已隨動態佈局移除） |
| `Scenes/TodayReviewAutoplayController.swift` | 137 | `@Observable @MainActor final class TodayReviewAutoplayController`，封裝 autoplay playback state / settings persistence / loop task。**`@Observable` 是契約不是風格**：4 個 playback 狀態由 `TodayReviewState` 的 computed property 投影給 `TodayReviewView.body` 讀，型別若無 registrar 則切 autoplay 不會 invalidate view（開啟方向被 loop 的 `session` mutation 延遲自癒、關閉方向永不自癒 → 播放列永久卡住）。把持有它的 `let` 改成 `var` 不能代替。`task` 必須 `@ObservationIgnored`（每卡 restart loop = 每卡兩次假通知）。`pauseForInterruption()` 只暫停不啟動且**刻意不自動恢復**。由 `TodayReviewAutoplayObservationTests` 釘住 |
| `Scenes/TodayReviewCollocationState.swift` | 29 | `struct TodayReviewCollocationState`，封裝 collocation explanation 的 scene-local mirror 與 entry mutation；讓 `TodayReviewView` 不再直接持有 explanation mirror / save 流程 |
| `Scenes/WordDetailSceneState.swift` | 193 | `@Observable @MainActor final class WordDetailSceneState`，封裝 presenterState、`actionError`（原 `linkError`，現為所有卡片層級動作共用的單一 banner）與 link / archive mutation orchestration；讓 `WordDetailSheet` 退回 scene 組裝與 routing。**共用 banner 的生命週期規則**：每個動作起手 `beginAction()` 清空，否則失敗訊息會活過後續的成功動作。`setArchived` 是 async（對齊 `KGVocabCoordinator.handleBatchArchive`），失敗回捲採 compare-and-swap + `!entry.isDeleted` 守衛——await 期間背景 pull 可能帶回權威值並 `markSynced()`，無條件寫回會用舊值蓋掉新鮮值且不再推送 |
| `Presentation/ReviewSessionStore.swift` | 117 | `struct ReviewSessionStore`，複習 session order 持久化；使用 `kg:<cardId>` / `local:<uuid>` persistence id、user scope 與 queue fingerprint |

### Domain Layer（純規則 / mutation helper）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Domain/VocabularyGraphLinkMutation.swift` | 106 | `struct VocabularyGraphLinkMutation`，集中 manual-link optimistic insert / commit / rollback、hide/unhide 與 delete rollback；`TodayReviewView` / `WordDetailSheet` 共用同一套 graph-link mutation 規則 |

### Presentation Models（UI 資料轉換）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Presentation/VocabularyEntryPresentation.swift` | 201 | `enum VocabularyEntryPresentation`，詞條 UI 模型 |
| `Presentation/WordRowPresentation.swift` | 138 | 詞列行 UI 模型；review state/relative label/progress 支援注入 `now` |
| `Presentation/WordDetailPresentation.swift` | 122 | `enum WordDetailPresentation`，詞條詳情 UI 模型 |
| `Presentation/CardPresentation.swift` | 148 | `struct CardPresentation` + `CardLinkGroupPresentation` |
| `Presentation/KnowledgeGraphPresentation.swift` | 203 | `KnowledgeGraphNode` / `KnowledgeGraphEdge` / `KnowledgeGraphTheme` / `enum KnowledgeGraphPresentation` |
| `Presentation/StatsPresentation.swift` | 99 | `enum StatsPresentation`；`buildSummary(..., now:)` 支援 frozen review clock |
| `Presentation/KGVocabSortOption.swift` | 28 | `enum KGVocabSortOption` |
| `Presentation/DictionaryDetailPresentation.swift` | 113 | `enum DictionaryDetailPresentation`，字典卡詳情 UI 模型：離線 payload 的義項／例句投影、來源與授權標示、分享文字組裝 |

### Scenes（獨立場景 View）

> Notebook 場景(`Scenes/NotebookListView.swift` / `NotebookListCoordinator.swift` / `NotebookEditSheet.swift`)獨立 boundary 見 `docs/reference/feature_boundary/notebook.md`,本表不重列。

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Scenes/KGVocabView.swift` | 348 | `struct KGVocabView: View`，Books & Vocab 詞彙列表場景；持有 `selectedRowID` 以在 desktop 三欄工作流中保留「目前右側 detail 對應哪一列」的中欄視覺狀態，filtered rows 移除該 id 時自動清空。整頁 error state 與離線 banner 都用固定重試文案，避免把低階 error message 直接暴露到 UI；分類/sort 使用 review pause reference date |
| `Scenes/TodayReviewView.swift` | 441 | `struct TodayReviewView: View` + `TodayReviewSession` + `TodayReviewRevealStage`；scene 組裝、sheet/shortcut chrome、外部 env wiring。版面編輯器掛在此的 `.toastSheet`：開啟時**先擷取當下卡片的 mode**（不是 sheet build 時的 current）、暫停 autoplay，關閉只翻 presentation flag，**不碰 reveal stage / currentIndex / session 持久化** |
| `Scenes/TodayReviewPhaseView.swift` | 176 | `struct TodayReviewPhaseView: View`，複習階段切換場景 |
| `Scenes/TodayReviewSwipeDeck.swift` | 299 | swipe deck：常駐三 card slot 組裝（`cardSlotView`/`deckDepthShell` 恆駐 depth-2）+ swipe gesture + fling settle 機械（settle 只重隨機被回收 slot 的 rotation）。fling 期間置 `dismissPhase == .animatingOut`，卡片離場後才清——`isCardInteractive` 因此涵蓋整個 fling/推進窗口 |
| `Scenes/TodayReviewCardSlot.swift` | 181 | Phase 4 常駐三 slot 純邏輯（slot = index % 3，active/preview/underPreview/hidden）：`TodayReviewCardSlotLayout`（role 指派 + 統一線性 depth transform/borderOpacity 純函數）+ `TodayReviewCardSlotModel`；settle = transaction 內三向 role 輪替、存活 slot 零內容 diff |
| `Scenes/TodayReviewPreviewData.swift` | 253 | preview 資料 |
| `Scenes/TodayReviewMetrics.swift` | 109 | TodayReview feature-local 版面 metrics(`static let`,~44 個)。動態佈局新增三顆共用 token：`foldSectionSpacingCompact`（精簡最後一階的 section 間距）、`foldMeaningLineSpacing`（等同卡片一直在畫的 5pt，預設佈局要重現現況就必須同號）、`revealZoneMinHeight`（「點一下展開」區的高度下限，solver 從正面預算扣的與畫面讓出的是同一顆） |
| `Scenes/ReviewCardLayout.swift` | 451 | **動態佈局的純值層**（無 SwiftUI import）：`ReviewCardFace` / `ReviewCardContentAvailability`（可用性與 profile 分離——缺資料只是本次不畫，不從使用者的偏好裡刪掉；`graphLinks` 恆可用，因為空連結時畫的是加連結入口，濾掉等於拿走唯一入口）/ `ReviewCardViewport`（容器高度 → contentHeight / revealZoneReserve / frontHeight / backHeight 的**單一來源**，正面預算刻意不隨 reveal 階段變動）/ `ReviewCardRenderPlan`（profile × mode × availability → 兩面欄位）/ `ReviewCardChrome`（padding 與 solver 扣的 inset 同一份）/ `ReviewCardLayoutSolver`（**O(fields) 純函式，每個 section 最多走訪一次、不留狀態**，固定精簡順序見下方「動態佈局契約」）|
| `Scenes/ReviewCardLayoutEditor.swift` | 260 | `struct ReviewCardLayoutEditor: View` + `ReviewCardLayoutEditorSheet`。**一個 View struct 供兩個入口共用**（複習 toolbar sheet + Settings navigation destination），只有外殼 chrome 不同；**不得 inline 回 presenter body**（真機 Debug 1MB main stack，同 `SettingsPresenter` 約束）。直寫 `ReviewCardLayoutStore`、不持 draft，所以卡片與編輯器不可能各說各話；勾選走 `ReviewCardField.toggling` 重排回 `canonicalOrder`（開關是可見性決定，永遠不是排序決定）|
| `Scenes/TodayReviewSessionSnapshotStore.swift` | 122 | `TodayReviewState` session snapshot 持久化 |
| `Scenes/ReviewFoldSurface.swift` | 108 | `struct ReviewFoldSurface` + `ReviewFoldChevronPill` |
| `Scenes/ReviewScoringState.swift` | 56 | 複習評分子狀態 |
| `Scenes/ReviewSessionPersistence.swift` | 271 | 複習 session 落地/恢復邏輯 |
| `Scenes/SelectionModeState.swift` | 47 | 列表多選模式狀態 |
| `Scenes/OverviewTab.swift` | 64 | `struct OverviewTab: View`，Vocab 入口 overview tab |
| `Scenes/AddLinkSheet.swift` | 313 | `struct AddLinkSheet: View`，KG 手動加連線 sheet；含字典區（搜尋 / 義項與例句選取 / 建卡並連結），流程狀態委派 `AddLinkCoordinator` |
| `Scenes/AddLinkCoordinator.swift` | 282 | `@Observable` 加連線流程狀態機；本地候選與字典搜尋共用一條 `searchGeneration` stale-guard，manual link 的 begin/create/commit 亦在此 |
| `Scenes/WordDetailSheet.swift` | 269 | `struct WordDetailSheet: View`，負責 scene 組裝、routing 與 sheet chrome；link / archive orchestration 委派 `WordDetailSceneState`。封存後**刻意不 dismiss**（圖示翻轉即回饋兼 undo）；刪除走 `confirmationDialog` 並**指名損失**（連結數取自 presenterState），確認後 `queueDelete` + dismiss；字典卡另有 `showDictionaryDeleteConfirmation` 一條分流。`offersLifecycleActions` 由 `showsInlineChrome` 推導：唯一為 false 的宿主 `LinkedCardOverlayStack` 自繪 header，封存鈕本就不渲染，若不一併關掉刪除，該疊層會變成「只能刪不能封存」 |
| `Scenes/WordDetailCopy.swift` | 25 | `enum WordDetailCopy`，詳情頁文案（慣例對齊 `NotebookListCopy`）。`deleteMessage(linkCount:)` 依連結數分流，無連結時不印「0 條」 |
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
| `Components/CardDocumentView.swift` | 505 | card document 主 View；重型 card document render path 含 `PerfLog` tick |
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
| `NotebookBindingList.swift` | 54 | `struct NotebookBindingList: View`（presentational，置於 Vocabulary/ 根）。單字本選擇清單，Reader（`ReaderNotebookPicker`，書綁定）與 Podcast（`PodcastNotebookPicker`，系列綁定）共用。`notebooks`/`selectedNotebookId`/`onSelect` 純資料注入；**刻意不標示「預設」** —— 所有單字本平權，每個容器（book/series）綁定即真相、無 magic 預設本。見 `NotebookBindable` |

### Overlay Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Overlay/LinkedCardOverlayStack.swift` | 82 | `struct LinkedCardOverlayStack: View`，關聯卡片 overlay |
| `Overlay/LinkReasonSheet.swift` | 73 | `struct LinkReasonSheet: View`，KG 連結理由 sheet（顯示 `KGCardLinkSummary`，提供導航/隱藏 link 動作） |

> Design token 已從 feature 本地 `Skin/VocabSkin.swift` 升格為全 app 共用 `AppSkin`(見 `ios/BooksAndVocab/Models/AppSkin.swift`),不再屬於 Vocabulary feature scope。

---

## 改動規則

- **新增列表 UI** → `Scenes/VocabularyListPresenter.swift` 或新增 Presenter extension
- **新增業務流程** → Coordinator（`VocabularyListCoordinator` / `SyncCoordinator` / `KGVocabCoordinator`）
- **新增 pure domain rule / optimistic mutation** → `Domain/`（不得直接塞回 scene / presenter）
- **新增 UI 資料模型** → `Presentation/` 下新增或擴充現有 Presentation enum/struct
- **新增可復用元件** → `Components/VocabShellComponents*.swift`（shell 級）或 `Components/VocabComponents.swift`（skin 級）
- **新增場景** → `Scenes/` 新增 View + Presenter + Coordinator，並在對應 container 的 Sheets extension 掛載
- **新增 design token** → `ios/BooksAndVocab/Models/AppSkin.swift`（全 app 共用；禁止在 feature 檔案裡硬編碼顏色/間距）
- **改複習卡片版面** → 先讀下方「動態佈局契約」。新增可選欄位＝改 `ReviewCardField`（含 `canonicalOrder`、`titleKey`/`captionKey` 與五個 lproj）+ `ReviewCardContentAvailability` + solver 的精簡階梯 + renderer；**版面幾何一律新增 `TodayReviewMetrics` token，不得在 solver 或 renderer 任一側寫死數字**——兩邊算的必須是同一顆

## State 邊界

- `TodayReviewState`：複習 scene owner，負責 orchestration；僅 `TodayReviewView` 持有，不外洩
- `TodayReviewSessionState`：純 session/navigation state，僅 `TodayReviewState` 持有
- `TodayReviewSessionPersistenceController`：session persistence helper，僅 `TodayReviewState` 持有
- `TodayReviewCardCache`：TodayReview rich-card cache helper，僅 `TodayReviewState` 持有
- `TodayReviewAutoplayController`：autoplay helper，僅 `TodayReviewState` 持有；狀態被投影給 view，故必須維持 `@Observable`
- `ReviewCardLayoutStore`（`ios/BooksAndVocab/Models/ReviewCardLayoutProfile.swift`，**Model 層、非本 feature 私有**）：複習卡片版面 profile 的唯一 owner。**只有一個 `EnvironmentKey`（`\.reviewCardLayoutStore`，`defaultValue = .shared`）**，app code 從不注入第二個 store——覆寫只出現在 `#Preview` 與測試。所以複習畫面改的與 Settings 顯示的必然是同一個物件；`ReviewCardLayoutSummary.titleKey` 的 預設／自訂 判定是**兩模式四面全深比較**（synthesized `Equatable`），不是只看目前這面
- `ReviewCardLayoutSolver` / `ReviewCardViewport` / `ReviewCardRenderPlan`：純值型，**不得持有狀態、不得引入 SwiftUI**；solver 必須維持 O(fields)（最多六欄）且每個 section 只走訪一次——它跑在翻卡/fling 路徑上
- `TodayReviewCollocationState`：collocation explanation substate，僅 `TodayReviewState` 持有
- `WordDetailSceneState`：Word Detail scene owner，持有 presenterState / link error 與 link mutation orchestration
- `VocabularyGraphLinkMutation`：Vocabulary feature-local pure domain helper，供多個 scene 共用 graph-link optimistic mutation / rollback 規則
- `SyncCoordinator`：同步流程狀態，僅 `SyncView` 持有
- `KGVocabCoordinator`：Books & Vocab 詞彙列表狀態，僅 `KGVocabView` 持有
- `VocabularyListCoordinator`：詞彙列表主導航狀態，由 `VocabularyListView` 持有
- Presentation models（`Presentation/`）：純值類型，可跨 layer 傳遞，但不持有 mutable state
- **容器↔單字本綁定 scope**（`NotebookBindable`，`ios/BooksAndVocab/Models/NotebookBindable.swift`）：每本書（`Book`）/ 每個 podcast 系列（`PodcastSeries`）綁定**恰好一本真實單字本**，開啟時以最近使用的真實本 seed 固化（`ensureBoundNotebook` + `canSeedBinding` gate：seed 須在 live 清單內已 settle，擋未同步 `"default"` sentinel）。固化後選詞 / highlight / cache scope 一律認 `resolvedNotebookId` 綁定本，**不再隨全域 active 漂移、無 magic 預設本**。`preferredNotebookId` 為純本機偏好；`resolvedNotebookId` 的 `?? activeNotebookId` 僅防禦性 last-resort（未經開啟流程就讀取），非主路徑。綁定本被刪除時由各 picker 的 `sanitizeStaleBoundNotebook` 清 nil、下次開啟 re-seed

## 字典卡邊界（V1）

字典卡住在本 feature，但**三個維度彼此獨立、不得互推**（欄位定義見 `docs/reference/card_format.md`，狀態流轉見 `docs/reference/sync_lifecycle.md`）：

- `cardRole` 決定它出不出現在一般 vocab 面與 pipeline；`reviewEligible` 決定它進不進複習與統計（字典卡恆 false）；`readerHidden` 決定 Reader／Podcast 高亮。**禁止用 `cardRole` 推導高亮**——高亮 eligibility 固定為「未 delete ∧ 未 archive ∧ `readerHidden == false`」。
- 列表 filter（全部／學習／字典）與排序在 `KGVocabCoordinator` / `KGVocabPresenter`；字典卡詳情走 `WordDetailSceneState` + `DictionaryDetailPresentation`，**不共用**單字卡的編輯面（字典卡不可改 meaning／note）。
- 「轉換成單字卡」只能由字典卡詳情明示觸發，UI 呈現 `queued` / `running` / `failed` / success 四態；失敗仍是字典卡、可重試。**無 learning → dictionary 降級路徑**，UI 不得提供。
- 同一 notebook 內同一正規化單字只能有一張 active card：已有 learning card 直接連結不降級；已有 dictionary card 重用既有卡與既有選定義項，**不靜默換例句**。
## 動態佈局契約（複習卡片）

改 `ReviewCardLayout.swift` / `TodayReviewPresenter+CardContent.swift` 前必讀。**版面規則**（前五條）由 `ReviewCardRenderPlanTests` / `ReviewCardBudgetParityTests` / `ReviewCardLayoutStoreTests` / `ReviewCardLayoutEditorTests` 釘住；**效能那條沒有單元測試守得住**，它的量測面是 `./ops/review_flip_probe.sh`，而該 gate **目前是紅的**（見該條）。

- **固定精簡順序，不可改動**：① 例句縮到目標詞前後各 3 詞 → ② 解釋降 2 行、再降 1 行 → ③ 搭配詞 2 列降 1 列（以 +N 表示）→ ④ 知識連結每組 2 項降 1 項、再降單列摘要 +N → ⑤ **最後才**降 section spacing 與 fold padding（走 `foldSectionSpacingCompact`，不是就地寫死）。
- **不會被自動隱藏的東西**：題目、答案、詞性、難度。使用者勾選的長內容至少保留 minimal 摘要；只有 Accessibility Dynamic Type 下連 minimal 都放不下，才啟用垂直捲動（`requiresScrollFallback`）。
- **natural 這一層就是「目前出貨的卡片」**：解釋 3 行、搭配詞 2 列、背面例句不截斷。若把它們當成「已經壓過的一層」，未動過的預設 profile 會比它要重現的畫面更鬆，得等階梯跑完才回到原樣。
- **正面預算不預留反面高度**，且不隨 reveal 階段變動（展開時區塊收合，但讓預算長大會在翻卡中途重解正面）。反面拿的是「同一份 contentHeight 扣掉正面實際佔用」——inset 只扣一次。
- **一份 chrome、一份 spacing**：solver 扣的 `chromeHeight` 由 `ReviewCardChrome.verticalInset(for:)` 給，renderer 畫的 padding 也由它給；solver 解出的 `sectionSpacing` 直接回傳給 renderer 畫，renderer 不得自己從 token 再推一次。
- **效能（目標，尚未達成 —— `review_flip_probe` 紅燈中）**：欄位資料在 `TodayReviewCardCache` 預先整理；fling 每幀不得重建 `CardDocument` 或重新遍歷 paragraphs。只有 profile / 寬度 / Dynamic Type / 卡片 identity 改變才重算（量測 cache key = `ReviewCardMeasurementKey`）。反面重內容維持 reveal 才 mount、collapse 動畫結束才 unmount。
  **已知缺口**：`reviewMeasurementProbes` 為了取三層高度，會在卡片內渲染**隱藏的量測副本**（每欄最多 3 份，六欄最多 18 份），而 cache key 含 `cardKey`（word + dateAdded）→ **每換一張卡就整批重量測，而且落在推進那一幀**。「只在 identity 改變時重算」在逐卡推進的情境下＝每張卡都重算。量測證據：`./ops/review_flip_probe.sh --simulator --release --dataset-file ops/fixtures/ui_worlds/marketing_demo.json --flips 30` 在 `3222aec3a`（solver 上線前）為 p95 16.667ms / 0 stalls，在 `7099f803f`（solver 上線）之後起 p95 33–34ms / stalls 7 之 30。修的方向是把量測移出關鍵幀（沿用 `TodayReviewCardCache` 既有的 prewarm window 預熱下一張），而不是放寬門檻。

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
