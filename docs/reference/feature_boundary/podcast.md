<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Podcast/
verified_against: e264e4ce
-->
# Podcast Feature Boundary

## 檔案清冊

### Container Layer（主場景 View）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastHomeView.swift` | ~354 | **podcast 頂層 section 入口（軸 B Phase 3）** `struct PodcastHomeView: View`，由 `ContentView` `AppPrimarySection.podcasts`（iOS TabView 第 2 / Catalyst sidebar）掛載。自有 `NavigationStack(path: $navigationPath)`（鏡射 `NotebookListView` path-bound root）；root 統一註冊 `navigationDestination(for: PodcastNavRoute.self)`（`.series→PodcastEpisodeListView`、`.episode→PodcastPlayerView`），**series→episode→player push 全在本 stack 完成**，不再寄生 `BookshelfView`（解架構債）。首頁 phase 由 `PodcastHomePhase.resolve` 分成 loading / error / empty / content：首次同步中顯示同步卡，list fetch failed 且本地無 series 顯示 retry error state，有既有 catalog 時保留 content。**內容為串流 shelf 堆疊**：`continueShelf`（繼續收聽，`@Query PodcastProgress`（updatedAt desc）跨 series 在記憶體 join episode→`PodcastContinueRailCard`，空則整段隱藏）+ `seriesGridSection`（所有節目 `LazyVGrid`，followed 排前 + star badge）。series 卡 / continue 卡一律 value-based `NavigationLink(value:)`（LazyV/HStack freeze 契約 PR #366/#368/#370/#373）。`.task(id: authManager.isLoggedIn)` 觸發 `syncPodcastCatalog(showToastOnFailure:warmAudioAfterSync:)`；pull-to-refresh 走同一路徑但不 warm audio。`toggleFollow` / `refreshPodcastCatalog` 自 `BookshelfView` re-home。卡片 tap feedback 共用 `BookshelfCardButtonStyle`（已提升 internal） |
| `PodcastPlayerView.swift` | ~49 | **薄 wrapper**：保留 feature 入口與測試相容的 static helper API（`fetchEpisode` / `resolveVocabularyContext` / `shouldPersist` / `isCompleted`），實際 UI 與生命周期 orchestration 下放到 `PodcastPlayerScene.swift` / `PodcastPlayerSupport.swift` |
| `PodcastPlayerScene.swift` | ~631 | 主播放器場景 orchestration。持有 `PodcastPlayerViewModel` / `ReaderTranslationHandler` / progress persistence / episode-switch state，負責 `.task(id: activeEpisodeId)` 換集、`scenePhase`/`onDisappear` 存檔、字幕設定 sheet、translation panel bridge、retry subtitle、auto-advance 與高頻 `PodcastProgressTicker` 隔離 |
| `PodcastPlayerAccessSurface.swift` | ~82 | player access chrome：`PodcastPlayerLockedGateView`（guest/login vs free/paywall 鎖定畫面）、`PodcastPlayerPreviewBanner`（3 分鐘 preview 升級條）、`PodcastPlayerSettingsButton`（toolbar glyph）。把 monetization / locked UI 從 session orchestration 抽離成明名 surface |
| `PodcastEpisodeListView.swift` | ~285 | 單集列表 + series 詳情容器 `struct PodcastEpisodeListView: View`。**串流「show page」hero（軸 B Phase 1）**：`heroHeader` = `PodcastSeriesHero`（沉浸式模糊封面 backdrop + 封面卡 + 標題 + meta，見下 Hero Components 條目）+ `heroContinue`（「繼續收聽」主角卡 `PodcastContinueCard`，取代舊全寬 CTA）。**episode → player 單欄 push（2026-06 #672 收斂）** — tap episode row / 繼續收聽主角卡一律 `NavigationLink(value: PodcastNavRoute.episode(...))`，由 **PodcastHomeView root 的 `navigationDestination(for: PodcastNavRoute.self)`** 接住 `PodcastPlayerView`（軸 B Phase 3 起；podcast 獨立頂層 section 後不再經 `BookshelfView`），所有 layout 皆然。`warmConnection` 走 `.simultaneousGesture(TapGesture)`。**heroContinue 鏡射 episodeRow 的 freeze 契約**：`PodcastAccess.heroAction(...)` 解析出的 `navigatesToPlayer` 為真→value-based `NavigationLink`、gate→plain `Button{handleLockedTap()}`。舊「regular 左右雙欄（右欄 inline player + 可拖拉分隔線 + `detailRouter.show` 即時 swap + 選中 row 染 `accentSubtle`）」已移除，連帶刪 `detailRouter` state / `.podcastDetailPresentation` modifier / `layoutMode`·`sizeClass`。`PodcastEpisodeActivation.activation(...)` 恆回 `.push`（保留作 episode 路由契約測試錨點）。value-based + root 統一註冊是 freeze-fix 契約（PR #366/#368/#370/#373，見檔頭註解）。⚠️ series / episode push 全在 **`PodcastHomeView` root path-bound `NavigationStack(path:)`**（軸 B Phase 3；舊 `BookshelfView` overlay master pane 已廢，見架構債） |
| `PodcastSentenceLevelView.swift` | ~157 | **薄 adapter**：保留句級字幕 feature 入口與 speaker-slot 決議，真正的 viewport/follow/selection orchestration 下放到 `PodcastTranscriptViewport.swift`，render token tree 下放到 `PodcastTranscriptColumn.swift`。主檔不再同時持有 scroll/follow state、bubble cell、underline engine 與 helper enums |
| `PodcastTranscriptViewport.swift` | ~264 | 句級字幕 viewport orchestration：原生 `ScrollViewReader` follow-scroll、initial positioning、manual drag disengage、selection dismiss catcher、Catalyst follow pill、DEBUG `logBoundary`。持有 `isFollowing` / `selectionState` / `scrollAnimationTask`，把互動層從 `PodcastSentenceLevelView` 本體抽出 |
| `PodcastTranscriptColumn.swift` | ~502 | transcript token tree：`PodcastTranscriptColumn` + `PodcastBubbleSkin` + `PodcastBubbleCell`，負責 speaker label、a11y、TextKit rect publish、詞庫螢光筆、逐詞底線 relay bars 與 per-cell `.equatable()` 邊界。這層是 render engine，不再和 viewport state 混檔 |

### Series → Episode → Player 導航（軸 B Phase 3 起：全在 `PodcastHomeView` stack）

> **series 全平台統一 value-based push。** podcast 抽離為獨立頂層 section 後（`PodcastHomeView`，見 Container Layer），series 卡片一律 `NavigationLink(value: PodcastNavRoute.series(...))` push 進 **`PodcastHomeView` 自己的** `NavigationStack(path:)`，episode→player 同 stack 續 push。不再有平台分支（舊 regular overlay master pane vs compact push 二分已廢）。
>
> ⚠️ **舊 `BookshelfView` overlay master pane workaround 已全刪**（軸 B Phase 3）：`@State selectedSeriesRemoteId` 疊加層、`PodcastSeriesActivation` / `.selectInline`、`PodcastDetailRouter.swift` 整檔、`BookshelfView` 的 `navigationDestination(for: PodcastNavRoute.self)` 與 toolbar 返回鍵均移除。獨立 stack 後不再需要那套「規避寄生 `BookshelfView` root」的 Catalyst overlay 防護。episode→player 單欄 push（#672 收斂）邏輯不變，只是 root 從 `BookshelfView` 換成 `PodcastHomeView`，並新增 auto-advance 換集（見 ViewModel `episodeFinishedTick` / `PodcastQueue`）。

### ViewModel Layer（播放狀態機）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerViewModel.swift` | ~375 | `@Observable @MainActor final class PodcastPlayerViewModel`,播放/暫停/seek + auto-pause-on-lookup + per-user progress LWW sync + sleep timer(`sleepTimerMode` / `sleepDeadline` / `DispatchSourceTimer` wall-clock;`.endOfEpisode` 由 audio engine load 換集 callback reset) + `bufferedEnd`(YouTube-style buffer overlay) + `subtitleState: PodcastSubtitleLoadState`(idle/loading/loaded/failed + inline retry) + `PodcastPlayerBootstrapPhase`(播放器啟動期 loading / missingEpisode / ready 分類) + `onSystemPause` / `onSystemResume` interruption hooks + `prefetchedDurationSec` + `audioHTTPHeaders` 透傳 + `playbackAnchor: PlaybackAnchor`(連續 playhead 外推錨點:mediaTime/wallClock/rate,handleTimeUpdate/seek/play/pause/cycleRate 刷新,驅動字幕底線連續引擎,見 `PodcastSentenceLevelView` 條目;**捲動已改原生 `scrollTo` follow,不再用此 anchor**) + `liveAnchor: PodcastLiveAnchor`(reference 型 playhead 鏡像,`playbackAnchor.didSet` 單點同步、`@ObservationIgnored`;讓字幕 view 的 EquatableView token 樹被每幀跳過時,underline 內層 TimelineView 仍能每幀讀到最新 anchor——見 `PodcastSentenceLevelView` 條目) + `episodeFinishedTick`(連續播放：`onPlaybackFinished` 自然播畢時 bump，view `.onChange` 觸發 `advanceToNextEpisode`；用 counter 而非 closure 以避 VM→view→box retain cycle，鏡射 `sleepTimerFiredTick`；`.endOfEpisode` 睡眠定時那次**不** bump → 播完本集即停) + `stop()`(session-internal teardown) vs `shutdown()`(terminal cleanup) |

### Domain / Integration（翻譯與詞彙橋接）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerSupport.swift` | ~49 | player 純 helper：`fetchEpisode` / `resolveVocabularyContext` / `shouldPersist` / `isCompleted`。供 `PodcastPlayerScene` 使用，`PodcastPlayerView` 只保留薄 wrapper 轉發給測試與其他呼叫點 |
| `PodcastVocabularyContext.swift` | 89 | `struct PodcastVocabularyContext: VocabularyContextProtocol`，連通 reader-parity 翻譯 + 加入詞庫 |
| `PodcastVocabHighlightResolver.swift` | ~30 | **字幕詞庫螢光筆比對（純函式，2026-06）**：`highlightedIndices(words:normalizedLookedUp:)` 算出字幕句中命中詞庫（含 inflections，由 `ReaderVocabularyContext.lookedUpWords` 展開）的 word index；`normalize` = 折疊彎撇號（U+2019→U+0027 直撇號）+ 小寫 + 去頭尾標點，**兩側對稱**比對（修字幕彎撇 vs 詞庫直撇的 don't/can't/I'm silent 不命中）。cell 端 `PodcastSentenceLevelView` 以命中 index + 逐詞 TextKit rect（`wordRects`）畫**常駐 background layer**（顏色/濃度/字底 32% 色帶取 `ReaderSettings.vocabHighlightPreferences`，對齊 Reader 的底線式 `.vocab-word` 而非整字高色塊；不受 `isCurrent‖isNext` gate 所有句子常駐、**選取時仍顯示**、`allowsHitTesting(false)` 不擋手勢）。播放逐字底線是另一個 overlay top layer（`PodcastTranscriptMarkLayer.playbackUnderline`），不可與詞庫 highlight 共用 overlay，避免 highlight 蓋掉跟隨底線；column 每 render 折疊一次 `normalizedLookedUp` 供各 cell 共用，cell `==` 納入命中集合、highlightPreferences、colorScheme 即加/刪詞庫或偏好變更會重繪。即時更新依賴 `PodcastPlayerView.body` 頂層 `let _ = translationHandler.lookedUpWords.count` 註冊 `@Observable` 依賴（否則讀取埋在 `playerContent(_:)` 內失效不及於 body，需重進該集才現）。單測 `BooksBrowserTests/PodcastVocabHighlightResolverTests.swift`（11 cases） |
| `PodcastAccess.swift` | ~75 | **分層授權 UX policy（純函式，鏡射後端 `podcast_access.py`）**：`PodcastTier{guest,free,pro}` + `tier(hasProAccess:hasToken:)`（pro 優先；有 token=free；無=guest，對齊後端 token 判別）、`isFreePreviewable`（`freePreviewEpisodeNumber=1`，純 ep-num policy 鏡射後端）、`canPlay(…previewAvailable:)`、`isPreviewPlayback(…previewAvailable:)`、`showsProLock(…previewAvailable:)`、`heroAction(tier:episodeNumber:previewAvailable:audioAvailable:hasProgress:allCompleted:) → PodcastHeroAction`（series hero 主 CTA 的純投影：評估序 lock→unavailable→preview→replay→resume→play；`PodcastHeroAction` enum 的 `navigatesToPlayer` 區分播放 vs gate，單測 `PodcastHeroActionTests.swift`）。後三者**額外**要求 `previewAvailable`：free 用戶僅在 ep1 真有 `preview.*` 資產時才視為可試聽，legacy/未回填 series 的 ep1（`previewAvailable=false`）顯 Pro 鎖而非導向後端 404 死路（client 比後端嚴一階以避免死巷；後端仍純依 ep_num 選 key）。**伺服器仍是安全邊界**，此為 UX 層先攔（鎖定 badge/登入/paywall/試聽標示），不靠樂觀請求解析 403。單測 `BooksBrowserTests/PodcastAccessTests.swift` |
| `PodcastQueue.swift` | ~30 | **連續播放佇列決策（純函式，軸 B Phase 3）**：`nextPlayable(in:after:tier:)` → 同 series `episodeNumber` 次大且 `audioAvailable` 者，過 `PodcastAccess.canPlay` gate；遇第一個有音訊但不可播的集即停（回 `nil`，**不**跳過鎖定集找更後面）→ free 播完 ep1 preview 不自動跨 Pro-only ep2、guest 不續播。`PodcastPlayerView.advanceToNextEpisode` 由 VM `episodeFinishedTick` 的 `.onChange` 驅動，命中即設 `overrideEpisodeId` → `.task(id: activeEpisodeId)` 接手換集。單測 `BooksBrowserTests/PodcastQueueTests.swift`（7 cases） |
| `PodcastSelectionRouting.swift` | 21 | **字幕選取單字 vs 片語分流（純函式）**：`isSingleWord(_:)`（`split(whereSeparator:\.isWhitespace).count == 1`,前後/全空白自然落空 → 非單字）+ `route(for:) → .word/.phrase`。`PodcastSelectableSentenceTextView` edit menu「翻譯」依此把單一詞導向 word path、多詞片語導向 phrase path（reader 靠手勢本質分流,podcast 所有選取同出一個 `UITextView` edit menu 故改以 token 數判定）。單測 `BooksBrowserTests/PodcastSelectionRoutingTests.swift`（5 cases） |
| `PodcastSelectableSentenceTextView.swift` | ~340 | **統一兩態字幕渲染器（③ 3-A,2026-06）**：平常態與選取態共用**同一個** `UITextView`（只 `isSelectable` 切換 → 零 reflow,消除選取跳版）。display 態逐詞 rect 由 `PodcastSentenceUITextView.layoutSubviews`（`LayoutKey` cache 守門）publish 給底線 overlay；長按 `UILongPressGestureRecognizer`(0.35s) `characterIndex(for:)` 反查 word index 進選取；selecting 態原生選取 + edit menu 翻譯/解釋（`L10n`）。**edit menu 詞彙互動對齊 reader（2026-06）**：「翻譯」依選取字數分流（`PodcastSelectionRouting.route`）——單字→`onWordSelection`（word path：`translateQuick` + 字根還原 + 詞庫去重 + 既有條目直接載入）、片語→`onTranslateSelection`（phrase path）；「解釋」對**單字 + 片語皆出現**（移除舊 `shouldOfferExplain` 單字 gate，鏡射 reader 的 gate-free edit menu，後端 explain 單一 prompt 通吃，不改）。M1 fallback flag `displayTextIsInteractive`（翻 false → display 態 inert,gesture 退 cell 層） |

### Streaming UI Components（軸 B：hero / shelf / 卡片）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastSeriesHero.swift` | ~250 | 兩個串流 hero 元件（皆純展示、不持有 navigation）：<br>**`PodcastSeriesHero`** — 沉浸式 series 標頭：ambient 模糊封面 backdrop（`coverColor` 漸層基底 + `coverImagePath` 存在時低透明模糊封面疊加，底部以 `LinearGradient → pageBackground` 融入無硬邊，`allowsHitTesting(false)` + `accessibilityHidden`）+ 浮起封面卡（`.appElevation(.z3)`）+ hero 標題 + 主持人/集數/總時長 meta（`metaText`/`formatTotalDuration` 自 PodcastEpisodeListView re-home）。<br>**`PodcastContinueCard`** — 「繼續收聽」主角卡（取代舊全寬 CTA）：play/lock disc（actionable=`brandHero`+`onBrandHero`、否則灰）+ 行動動詞 eyebrow（依 `PodcastHeroAction` 映射既有 L10n key）+ 目標單集 `displayTitle` + 進度條（`ProgressCapsule`，僅 `.resume`）+ 還剩 `podcast.continue.remaining`（`monospacedDigit`）。**navigation 由 owner（PodcastEpisodeListView.heroContinue）包**，鏡射 episodeRow 的 value-based-push / plain-Button freeze 契約，自身絕不建 NavigationLink。clock 用共用 `PodcastClock.format`。附 `#Preview` 涵蓋 hero + 6 種 action 狀態 |
| `PodcastShelf.swift` | ~190 | **串流首頁元件（軸 B Phase 2）**：`PodcastShelf<Content>`（泛用水平 carousel：section 標題 + `ScrollView(.horizontal)` + `LazyHStack`，codebase 首個泛用橫排容器）+ `PodcastContinueRailCard`（繼續收聽卡：直式封面縮圖 + 右下 play disc + series/episode 標題 + `ProgressCapsule` + 還剩 `monospacedDigit`，固定寬 150）。皆純展示、owner 以 value-based `NavigationLink` 包（freeze 契約）。clock 用 `PodcastClock.format`。Scenario baseline×5（resume/no-progress/long/large-numbers/a11y3，見 `PodcastShelfCardsScenarios`） |
| `PodcastSeriesCard.swift` | ~85 | `struct PodcastSeriesCard: View` — series grid 卡（2:3 封面 + waveform/追蹤 badge + 標題 + `主持人 · N 集` 串流 meta 單行 tail 截斷，無主持人退純集數）。軸 B Phase 3 自 `Bookshelf/Components/` 遷入本 feature 目錄（現由 `PodcastHomeView` grid 使用） |

### Streaming / Offline Services（ios/BooksBrowser/Services/）

| 檔案 | 說明 |
|------|------|
| `PodcastAssetPreloader.swift` | @MainActor singleton；warm AVFoundation HTTP/2 連線（tap-on-row + bookshelf-appear）；LRU-5, 60s TTL；失敗即 evict |
| `PodcastDownloadManager.swift` | @MainActor @Observable singleton；URLSession.background 跑離線下載；落地 `episode.localAudioPath`（Documents/podcast-downloads/<seriesId>/<remoteId>.mp3）；progress / failed 由 `@Query` 觀察 |
| `PodcastSyncService.swift` | @MainActor；`syncAll(context:)` 拉取後端 podcast catalog 並 upsert series/episode。**自我防禦**：list fetch 失敗即 skip、空 server list（`/api/podcasts` 回 `[]`，S3 index.json 短暫讀不到時）視為非權威 → reconcile 跳過 series tombstone（不 soft-delete），對稱 episode 層 empty-episodes 守衛、不 throw。**封面快取**：upsert 後以 bounded concurrency 跑 `cacheCoverIfNeeded`，把 `coverImageURL`（有值才）認證下載成 `Documents/podcast-covers/<sid>_<v>.png`（legacy 無 `?v=` 時退 `<sid>.png`）→ 寫 `PodcastSeries.coverImagePath`（HTTP 2xx + `image/png` + PNG magic 守門、best-effort、失敗退程序化封面、不 abort sync）；**server 撤回封面**（`coverImageURL` 轉 nil/空）時 `upsertSeries` 清掉 `coverImagePath` + best-effort 刪當前 path/legacy `<sid>.png`，避免 stale 快取永久渲染且不以 prefix 誤刪其他 `_` series；`LocalDataCleanerService.purgePodcastCovers` 於 logout/account-switch 清除 disk + memory cover cache。**觸發來源**：`PodcastHomeView` `.task`/`.refreshable` + `KGService.backgroundSync`（Phase 3，序執行於 vocab pull 後，見 §同步觸發） |

### 同步觸發

podcast catalog 同步現有兩條觸發鏈：

1. **PodcastHomeView 局部觸發** — `.task(id: authManager.isLoggedIn)`（登入狀態翻轉時同步）+ `.refreshable`（下拉重試）。首頁以 `PodcastHomePhase` 區分 loading / error / empty / content。
2. **`KGService.backgroundSync` Phase 3**（`KGService+Sync.swift`，序執行於 vocab pull 之後）— 共用所有既有 resync 觸發：post-login / scenePhase→active / ⌘R menu / Settings 手動同步。補上局部 task/refresh 沒跑到時 podcast catalog 仍可由全域同步復原的路徑（書為本地 `@Query` 故恆在）。token 過期已由 vocab pull 的 401 分支提早 return。

### metadata.json contract

- `episodes[].subtitleContent: String?` 由 `ops/podcast_upload.sh` 嵌入；iOS `PodcastEpisode.inlineSubtitle` 直接消費，跳過 `/api/podcasts/{sid}/{ep}/subtitle` fetch
- `episodes[].localAudioPath: String?` (SwiftData only, 不在後端 JSON) — 由 DownloadManager 填寫；PlayerView 認到即用 file:// URL 跳過認證
- `coverImageURL: String?` 由 `ops/podcast_upload.sh`（full publish）**或** `ops/podcast_cover_publish.py`（封面重發布,audio-decoupled）寫入（`cover` stage 有產 `cover.png` → `/api/podcasts/{sid}/cover?v=<sha16>`，否則 `null`）；也在 `index.json` series entry（series list 即可顯示封面）。backend 忽略 query 仍 proxy 同一張 `<sid>/cover.png`；iOS 用 `v` token 命名本地快取，替換既有封面可於下次 catalog sync 自動刷新，否則退 `color`/`coverPattern` 程序化封面
- `episodes[ep1].previewAvailable: Bool` + `previewDurationSec: Int`（free-tier 試聽，**僅 ep_01**）：`ops/podcast_upload.sh` 對 ep_01 以 `ffmpeg -t 180 -c copy` stream-copy 出 `ep_01/preview.<fmt>`（同 container/codec、無損）並寫此二欄；既有 series 由 `ops/podcast_preview_backfill.py`（bucket-driven、audio-decoupled、dry-run 預設 / `--execute` / `--check` drift）回填。backend `audio` 端點對 free tier 服務此 `preview.<fmt>` 物件（見 `tech_index.md` podcast_access），**不**對完整檔做 byte 截斷（progressive MP4 單 moov 宣告全長，截 byte 會讓 AVPlayer 報錯而非乾淨停止）。preview 欄位在 `episodes` 內，`index.json` 會 strip，故不影響 series-list view

### Sub-views（UI 元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastControlsView.swift` | ~150 | 播放/暫停/快轉/速度控制列（brandHero CTA + appCompactAction；15s ghost 按鈕含 44pt 最小 tap target；seek bar 整條 20pt hit area 可點/拖，幾何換算由 `PodcastSeekBarGeometry` 測試鎖住） |
| `PodcastEpisodeRow.swift` | 130 | 單集 list row（標題、長度、追蹤 chevron），row 節奏 token 對齊 `WordRow` |
| `PodcastSubtitleView.swift` | 55 | 字幕單行渲染 |
| `PodcastSettingsPopover.swift` | ~145 | 字幕大小 S/M/L/XL/XXL + highlight 顏色 swatch（寫回 shared `ReaderSettings.vocabHighlightColorPreset`）+ auto-pause toggle + 逐字跟隨 toggle(`@AppStorage("podcast.wordFollowEnabled")`) + 睡眠定時 Picker(off / 5 / 15 / 30 / 60min / endOfEpisode)含 `TimelineView` MM:SS 倒數。**呈現方式**:`PodcastPlayerView` 以 `.sheet`(`NavigationStack` + 完成鈕)叫出，**非** `.popover`——toolbar-anchored `.popover` 在 Mac Catalyst present 過場 trap(`ops/catalyst_lint.sh` 守門)。觸發鈕依 layout 自判:compact 走 `ToolbarItem(.topBarTrailing)`,regular inline 走 `inlineSettingsButton` content overlay(player 不再自帶內層 NavigationStack,見 `PodcastPlayerView` 條目) |
| `PodcastFollowToggle.swift` | 49 | series 追蹤 toggle（已追蹤浮上書庫頂端） |
| `PodcastBadge.swift` | 18 | 「已追蹤」「新集數」狀態 badge |
| `SpeakerAccentBar.swift` | 42 | 多角色播客的口音/語者識別條 |
| `SubtitleRenderState.swift` | 57 | 字幕高亮狀態（current sentence index + 啟動瞬間 layout）|
| `PodcastTextKitWordRects.swift` | ~95 | TextKit 逐詞 rect 純函式（③ 3-A）：`wordRanges`（位置式 word→`NSRange`,依 `sentence.text == words.joined(" ")`）+ `resolve`（`NSLayoutManager.boundingRect`,越界/zero 回 nil）+ `LayoutKey`（text+font+width cache 守門）。統一 `UITextView` 的底線 rect 來源,取代舊 `CachedFlowLayout`+`WordFrameKey` anchorPreference |

### Token Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerMetrics.swift` | ~50 | 播放器 feature-local 尺寸常數 + `PodcastSeekBarGeometry` 純幾何 helper（track position → time / progress width / buffered width）+ `PodcastClock.format`（`m:ss` / `h:mm:ss` 時鐘格式，locale 無關；`PodcastContinueCard` / `PodcastContinueRailCard` 共用，消除先前兩處重複的 `formatClock`） |

---

## 改動規則

- **新增播放器控制 UI** → 抽到 `PodcastControlsView` 或新元件,不要繼續長 `PodcastPlayerView`
- **新增字幕呈現邏輯** → `PodcastSentenceLevelView` 或 `PodcastSubtitleView`,逐詞底線幾何抽到 `PodcastTextKitWordRects`（rect 解析）+ `PodcastUnderlineGeometry`（bar）,字幕高亮狀態抽到 `SubtitleRenderState`
- **新增播放狀態（speed / region / queue）** → `PodcastPlayerViewModel`,View 不放 mutable state
- **新增 series / episode 列表 UI** → `PodcastEpisodeListView` + `PodcastEpisodeRow`；列表卡片骨架走共用 `ListSectionCard`（UIComponents，與單字列表共用，見 `docs/reference/ui/components.md` §List Shell），divider 由 caller 在 `ForEach` 內插
- **改 podcast 頂層 section / series 導航** → `PodcastHomeView`（自有 `NavigationStack(path:)` + shelf 堆疊）+ `ContentView.AppPrimarySection`。series / episode / player 全 value-based push 在 `PodcastHomeView` stack，`navigationDestination(for: PodcastNavRoute.self)` 統一掛 root。**不要**重建 overlay master pane / `selectedSeriesRemoteId` / `PodcastDetailRouter`（軸 B Phase 3 已廢）。新增首頁 shelf → `PodcastShelf`（泛用橫排）+ 對應 rail card
- **改連續播放 / auto-advance** → 決策走 `PodcastQueue.nextPlayable`（純函式 + `PodcastAccess.canPlay` gate），觸發走 VM `episodeFinishedTick` → `PodcastPlayerView.advanceToNextEpisode`（設 `overrideEpisodeId`，**勿**改用 nav push 以免堆疊 nav stack）。entitlement 邊界改動同步 `PodcastQueueTests`
- **新增 user-tunable 播放參數(字幕 / 跟隨 / 計時器 等)** → `PodcastSettingsPopover`(集中所有 user-tunable 播放參數;非字幕專屬)
- **新增詞彙互動** → `PodcastVocabularyContext`(reader-parity:任何 reader 詞彙流程都要在此鏡像)
- **動分層授權（誰能播哪集 / 鎖定呈現）** → policy 一律走 `PodcastAccess`(勿在各 view 散寫 tier 條件)；改 free 可播範圍同步後端 `podcast_access.FREE_PREVIEW_EP_NUM` + `PodcastAccess.freePreviewEpisodeNumber` + `PodcastAccessTests`。鎖定 row 用 `Button{paywall/login}`（**不可**用 closure-based `NavigationLink`，會重現 LazyVStack freeze）；可播 row 維持 value-based `NavigationLink(value:)`。player 須保留防禦式 gate（`canPlay` false → `lockedGateView` 且 `loadEpisode` early-return，涵蓋 deep-link 直達）
- **新增 metric token** → 跨 feature 用升 `AppMetrics`;單 feature 用留 `PodcastPlayerMetrics`
- **訂閱進度持久化等高頻(15Hz)`@Observable` 狀態** → **絕不**把 `.onChange(of: vm.currentTime)`／類似高頻讀取掛在 `PodcastPlayerScene.body`／`playerCore`／`playerContent` 等父層,必須隔離進只渲染 `Color.clear` 的葉子(`PodcastProgressTicker` 模式)。否則 `@Observable` 的 per-view-body 失效會讓父 body 每 tick 重求值、連鎖重建字幕子樹,字幕的 `EquatableView` 優化(`PodcastTranscriptColumn.equatable()`)會被父層 invalidation 架空 → 捲動卡頓 + follow 捲動失效

## State 邊界

- `PodcastPlayerViewModel`：播放器狀態機(playing / current ep / progress / sentence highlight),由 `PodcastPlayerScene`（掛在 `PodcastPlayerView` 下）持有,**不**外洩至 series 列表
- `SubtitleRenderState`：字幕 layout 快取,由字幕 view 持有
- per-user progress(`/api/podcasts/.../progress`)走 backend LWW,iOS 端只 cache;不放 ViewModel mutable state
- `PodcastVocabularyContext` 為 protocol 橋接,持有者是上層 view;具體儲存交由共用 `VocabularyService`

## 共用依賴

| Token | 用途 |
|-------|------|
| `AppTheme` | 色彩,`@Environment(\.appTheme)` |
| `AppMetrics` / `AppShellMetrics` | 間距、尺寸 |
| `AppMotion` | 動畫 token(字幕跳動、按鈕回饋) |
| `AppTransition` | 過渡動畫 |
| `PodcastPlayerMetrics` | Podcast 專屬尺寸常數 |
| `VocabularyContextProtocol` | reader-parity 翻譯/查詞橋接 |
| `VocabHighlightPreferences` | Reader-shared 詞庫 highlight 偏好；PodcastSubtitleView 由 `ReaderSettings` 注入至句級字幕 |

## Storage backend(2026-06 Track B)

- **音頻格式**: AAC/M4A(128k,`+faststart`)。`.mp3` 仍可播,backend `audio.m4a` → `audio.mp3` fallback 涵蓋過渡期 series。
- **位置**: Lightsail Object Storage `s3://kg-podcasts-prod/{series_id}/{metadata.json, cover.png(選), ep_NN/{audio.m4a,subtitle.srt,script.md}}`(`cover.png` 為 series 層封面,`cover` stage 有產才有;舊 disk-mode 路徑 `data/podcasts/...` 仍由 backend 處理,當 `PODCAST_BUCKET` env 未設時)。
- **iOS 變更**: 零。`AVURLAssetHTTPHeaderFields` 帶 `Authorization: Bearer`,backend 走 proxy 模式(不 302 redirect 到 presigned URL,避免 AWS sig + Bearer header 衝突 → 403)。
- **Range 支援**: backend 把 `Range` header 原樣轉給 S3 `get_object(Range=...)`,S3 回 206 + `Content-Range`,backend 透傳。
- **過渡期回退**: `PODCAST_BUCKET` env unset → backend 改走 disk fallback,舊 series 仍可播。
- 詳見 `docs/sop/podcast_pipeline.md §Storage`。

## 架構債

- ~~**podcast 無頂層 section、被迫經 `BookshelfView` 進入**~~ **（軸 B Phase 3 已解）**：podcast 現為獨立頂層 section `PodcastHomeView`（`ContentView.AppPrimarySection.podcasts`，iOS TabView 第 2 + Catalyst sidebar），自有 `NavigationStack(path:)`；series→episode→player push 全在 podcast 自己的 stack，不再寄生 `BookshelfView` root，連帶刪除整套 overlay master pane workaround（`selectedSeriesRemoteId` / `PodcastSeriesActivation` / `PodcastDetailRouter.swift`）。series 啟動全平台統一 value-based push。
- **series 詳情仍是 `PodcastEpisodeListView` 全頁 push，非平台原生 `NavigationSplitView`。** 未來可評估以原生 split 呈現 series master-detail，但需先驗證 Catalyst 巢狀 split（`ContentView` 已用 `NavigationSplitView`）穩定性，本輪不做。

## 相關 doc

- `docs/reference/feature_boundary/reader.md` — reader 翻譯流程,podcast `VocabularyContext` 必須 mirror
- `docs/reference/sync_lifecycle.md` — 詞彙加入後的 sync 規則(**SoT**)
- `docs/sop/backend.md` — `/api/podcasts*` endpoint 與 progress LWW 後端細節
- `docs/sop/podcast_pipeline.md` — pipeline(synthesize → upload → S3)
- `docs/reference/product_surface.md` §Podcast player — 已實作功能清冊(避免重做)
