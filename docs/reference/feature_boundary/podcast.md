<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Podcast/
verified_against: 7d86b984
-->
# Podcast Feature Boundary

## 檔案清冊

### Container Layer（主場景 View）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerView.swift` | ~590 | 主播放器容器 `struct PodcastPlayerView: View`，audio + 字幕同步 + 翻譯面板 + 控制列。**設定鍵 chrome 依 `horizontalSizeClass` 自判，不再自帶內層 `NavigationStack`**：compact（iPhone push detail，有 ambient push nav bar）設定鍵走 `ToolbarItem(.topBarTrailing)`；regular（iPad/Catalyst inline 右欄，無專屬 nav bar）設定鍵改 `inlineSettingsButton` content overlay（`.overlay(alignment: .topTrailing)` 掛在 `playerCore` 層，覆蓋全狀態 loading/error/missingEpisode/ready，與 compact toolbar 對齊）。tab-bar 顯隱由 `layoutMode.usesInlineDetail` 決定（inline 不隱藏、compact 全屏才隱藏；Catalyst 無 tab bar 略過）。⚠️ 移除了舊 `wrapInNavigation` 參數——inline 曾傳 true 自帶 `NavigationStack` host `.topBarTrailing`，但該內層 stack 嵌在 BookshelfView 外層 `NavigationStack` subtree 內，會持久破壞外層 value-based push（NAVDBG 坐實：顯示過 inline player 後 reader 永久無法 push，內層 stack 銷毀後也不恢復 — Catalyst SwiftUI 缺陷）。啟動期透過 `PodcastPlayerBootstrapPhase` 區分未嘗試載入、已嘗試但 SwiftData 缺 episode/series、播放器 ready，避免 missing local row 時永久 spinner。<br>**⚡ 高頻訂閱隔離(scroll-freeze 上游根治)**:進度持久化的 15Hz `currentTime` 訂閱**絕不可**直接 `.onChange(of: vm.currentTime)` 掛在 `playerCore`／`playerContent`／`PodcastPlayerView.body`——`@Observable` 失效粒度是 per-view-body,`.onChange` 的 `of:` 在 body 求值時被讀取,等於讓整個 player body 訂閱 currentTime,每 tick 重求值 → `playerContent`(`@ViewBuilder` func，無 diff 邊界)連鎖重建非 Equatable 的字幕子樹 → 主線飽和(卡頓)+ follow 捲動失效。字幕子樹的 `.equatable()`(見 `PodcastSentenceLevelView` 條目)只擋最內層 `PodcastTranscriptColumn`,被這條**父層** invalidation 架空。修法:把 currentTime 訂閱關進只渲染 `Color.clear` 的葉子 `private struct PodcastProgressTicker`(`.background(...)` 掛),每 tick 只重求值該無子樹葉子(O(1)),父 body 與整條字幕子樹解放。`onTick` 仍 `state == .playing` gate,持久化節流由 `saveProgressIfNeeded` 的 `lastSavedTime` 負責 |
| `PodcastEpisodeListView.swift` | ~360 | 單集列表 + series 詳情容器 `struct PodcastEpisodeListView: View`。**episode → player 單欄 push（2026-06 #672 收斂）** — tap episode row / 頂部開始|繼續播放 CTA 一律 `NavigationLink(value: PodcastNavRoute.episode(...))`，由 **BookshelfView root 的 `navigationDestination(for: PodcastNavRoute.self)`** 接住 `PodcastPlayerView`，所有 layout（含 Mac/iPad regular）皆然。`warmConnection` 走 `.simultaneousGesture(TapGesture)`。舊「regular 左右雙欄（右欄 inline player + 可拖拉分隔線 + `detailRouter.show` 即時 swap + 選中 row 染 `accentSubtle`）」已移除，連帶刪 `detailRouter` state / `.podcastDetailPresentation` modifier / `layoutMode`·`sizeClass`。`PodcastEpisodeActivation.activation(...)` 恆回 `.push`（保留作 episode 路由契約測試錨點）。value-based + root 統一註冊是 freeze-fix 契約（PR #366/#368/#370/#373，見檔頭註解）。⚠️ series 層 master pane（非本 episode 軸）的 pop-to-root 防護仍依賴 **BookshelfView root 為 path-bound `NavigationStack(path:)`**（見 `bookshelf.md` Navigation 契約） |
| `PodcastSentenceLevelView.swift` | ~430 | 句級字幕 + 長按整句翻譯 + 點詞查詞 + follow-mode pill `struct PodcastSentenceLevelView: View`（iPhone/iPad：拖曳隱式脫離 follow，pill 僅在脫離時顯示；Mac Catalyst：滑鼠滾輪/觸控板 indirect scroll 不觸發 DragGesture，pill 常駐為明確 toggle「停止跟隨 ⇄ 追隨當前」，邏輯在 `shouldShowFollowControl`）。**逐字底線為連續引擎(非離散);自動捲動為原生 ScrollView 離散 follow**：current 句逐詞底線是**單一 capsule**,由 `TimelineView(.animation(paused: !isPlaying))` 每幀以 `PodcastPlaybackClock.projectedTime` 外推 playhead → `PodcastWordProgress.locate` → `PodcastUnderlineGeometry.bar` 連續定位(同行詞間 lerp、跨行不橫拉);word 幾何走 `WordFrameKey` anchorPreference,rects 每 layout pass 解析一次、TimelineView 只 lerp(不重排 `CachedFlowLayout`)。取代了舊「per-word `.overlay(Capsule)` + `.animation(value: highlightedWordIndex)`」的逐字 snap(在 <130ms 短詞會 strobe)。`wordFollowEnabled==false` 時 overlay closure 不畫底線。自動捲動走**原生 `ScrollView` + `ScrollViewReader` + `LazyVStack`**(僅 realize 在屏氣泡):follow = `onChange(of: currentId)` → `withAnimation(AppMotion.podcastFollowScroll){ proxy.scrollTo(currentId, anchor:.center) }`,**每句界一次 animated `scrollTo`**(離散,非每幀 offset)。進場置中走 `.task`(等 LazyVStack realize 再 `scrollTo`;`onAppear`/`onChange` 對 mount 當下值會 no-op);episode swap 由 `onChange(of: PodcastTranscriptIdentity(sentences:))` 重置中;re-engage 翻 `isFollowing` flag → `onChange(of: isFollowing)` 動畫捲回。手動瀏覽走**原生捲動**(GPU 合成、原生慣性、lazy realize);iPhone/iPad 輕量 `simultaneousGesture(DragGesture(minimumDistance:8))` 只翻 `isFollowing=false`;**Mac Catalyst 觸控板 indirect scroll 不觸發 DragGesture → pill 常駐為明確 toggle**(此點不變)。<br>**⚡ scroll-freeze 根治(根因史)**:舊「offset-driven 連續置中」引擎(非 lazy VStack + per-sentence `GeometryReader`/`SentenceCenterKey` 在 named `transcriptSpace` 量中心 + 外層 `TimelineView(.animation)` 每幀算 `PodcastScrollGeometry.centerOffset` 套 `.offset` + 自訂 `DragGesture`/`clampOffset`/`seedManualOffsetFromFollow`)**進場即凍**——三段真機單變數實驗(30 句仍凍 / 拿掉 TimelineView 警告消失 / 換原生 ScrollView 流暢)定位根因為 offset+per-frame-TimelineView 引擎本身,**非整集實體化成本**。整個 offset 引擎連同上述符號與 `PodcastScrollGeometry`(centerOffset/sentenceFraction)+ `PodcastScrollGeometryTests` 已刪。<br>**`.equatable()` 保留但語境改變**:token 樹仍抽成 `private struct PodcastTranscriptColumn: View, Equatable` 並 `.equatable()` 包起,其 `==` 比 **O(1) `PodcastTranscriptIdentity`(count + firstStart + lastEnd)** + sentence-level `currentId` / `selectionState` / `subtitleSize` / `wordFollowEnabled` / `isPlaying`,**刻意排除 playhead**——現用途是防 token-irrelevant 父重評(如 `isFollowing` flag 翻動)+ episode swap 偵測,而非舊「外層 follow TimelineView 每幀跳過」。playhead 走 reference 型 `PodcastLiveAnchor`(`viewModel.liveAnchor`,`playbackAnchor.didSet` 單點鏡像、`@ObservationIgnored`),underline 內層 `TimelineView` 每幀讀 `liveAnchor.value` 取最新 playhead,即使父 Equatable body 被跳過也不凍。`speakerSlots` 在 `body` hoist 一次;speaker→tint 抽 `PodcastSpeakerTint`(column 與 pill 共用)。`PodcastTranscriptIdentity` 純函式單測 `PodcastTranscriptIdentityTests` |

### Series Master Pane（Mac/iPad regular overlay）

> **series 層**(非 episode 層,見下方註):regular（iPad/Mac Catalyst）master pane 為疊加在 `BookshelfView` 恒定 root content 之上的 overlay pane，非 root-content swap、非 push。 點 series 卡片**不 push**——由 `BookshelfView` 的 `@State selectedSeriesRemoteId` 把 `PodcastEpisodeListView` 作為**疊加層**渲染在恒定的 bookGrid 之上（pane 畫不透明背景蓋住下方 grid）。顯示/隱藏只 mutate 這個 overlay layer，bookGrid 的 NavigationStack root identity 不受擾動，故 reader push 始終可用。如此既避免 Catalyst 「safeAreaInset 擾動外層容器 → NavigationStack 子樹 remount → 集數列表被 pop」的崩潰，也消除舊 `if/else` 在 bookGrid ↔ PodcastEpisodeListView 之間替換 root content 帶來的 root-swap identity 隱患（NAVDBG log 坐實；對齊 `NotebookListView` root-恒定模式）。series 層 push 只留給 compact（iPhone）。決策點 `PodcastSeriesActivation.activation(seriesRemoteId:layoutMode:)`（`PodcastDetailRouter.swift`）：regular→`.selectInline`、compact→`.push(.series)`。regular 返回入口為 `BookshelfView` toolbar `.topBarLeading` chevron-left；regular→compact 翻轉時 `selectedSeriesRemoteId` reset nil。
>
> ⚠️ **episode → player 不再走 master-detail。** 2026-06 #672 把 episode-list → inline player 雙欄收斂為單欄 push（見上方 `PodcastEpisodeListView` 條目）：刪 `@Observable PodcastDetailRouter` class（episode selection state）+ `\.podcastDetailRouter` EnvironmentKey + 整檔刪 `PodcastDetailPresentation.swift`（含其 `DraggableDivider` callsite + `@AppStorage("kg_podcast_panel_width")` + 右欄 `safeAreaInset`）。本層僅剩 series overlay pane 一個雙欄面。

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastDetailRouter.swift` | 52 | **檔名沿用，但 `PodcastDetailRouter` class 已於 #672 移除**——現僅含 `PodcastSeriesActivation`（series 層 compact push vs regular `.selectInline`，**維持原狀**）。`PodcastEpisodeActivation` 已隨 inline 雙欄一併刪除；episode → player 恆走單欄 push（見 `PodcastEpisodeListView` 條目）。episode selection state / `\.podcastDetailRouter` environment 已隨 inline 雙欄一併刪除 |

### ViewModel Layer（播放狀態機）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerViewModel.swift` | ~375 | `@Observable @MainActor final class PodcastPlayerViewModel`,播放/暫停/seek + auto-pause-on-lookup + per-user progress LWW sync + sleep timer(`sleepTimerMode` / `sleepDeadline` / `DispatchSourceTimer` wall-clock;`.endOfEpisode` 由 audio engine load 換集 callback reset) + `bufferedEnd`(YouTube-style buffer overlay) + `subtitleState: PodcastSubtitleLoadState`(idle/loading/loaded/failed + inline retry) + `PodcastPlayerBootstrapPhase`(播放器啟動期 loading / missingEpisode / ready 分類) + `onSystemPause` / `onSystemResume` interruption hooks + `prefetchedDurationSec` + `audioHTTPHeaders` 透傳 + `playbackAnchor: PlaybackAnchor`(連續 playhead 外推錨點:mediaTime/wallClock/rate,handleTimeUpdate/seek/play/pause/cycleRate 刷新,驅動字幕底線連續引擎,見 `PodcastSentenceLevelView` 條目;**捲動已改原生 `scrollTo` follow,不再用此 anchor**) + `liveAnchor: PodcastLiveAnchor`(reference 型 playhead 鏡像,`playbackAnchor.didSet` 單點同步、`@ObservationIgnored`;讓字幕 view 的 EquatableView token 樹被每幀跳過時,underline 內層 TimelineView 仍能每幀讀到最新 anchor——見 `PodcastSentenceLevelView` 條目) + `stop()`(session-internal teardown) vs `shutdown()`(terminal cleanup) |

### Domain / Integration（翻譯與詞彙橋接）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastVocabularyContext.swift` | 89 | `struct PodcastVocabularyContext: VocabularyContextProtocol`，連通 reader-parity 翻譯 + 加入詞庫 |
| `PodcastSelectableSentenceTextView.swift` | 167 | `UIViewRepresentable` 包 `UITextView` 提供 word-level tap + phrase 長按 |

### Streaming / Offline Services（ios/BooksBrowser/Services/）

| 檔案 | 說明 |
|------|------|
| `PodcastAssetPreloader.swift` | @MainActor singleton；warm AVFoundation HTTP/2 連線（tap-on-row + bookshelf-appear）；LRU-5, 60s TTL；失敗即 evict |
| `PodcastDownloadManager.swift` | @MainActor @Observable singleton；URLSession.background 跑離線下載；落地 `episode.localAudioPath`（Documents/podcast-downloads/<seriesId>/<remoteId>.mp3）；progress / failed 由 `@Query` 觀察 |
| `PodcastSyncService.swift` | @MainActor；`syncAll(context:)` 拉取後端 podcast catalog 並 upsert series/episode。**自我防禦**：list fetch 失敗即 skip、空 server list（`/api/podcasts` 回 `[]`，S3 index.json 短暫讀不到時）視為非權威 → reconcile 跳過 series tombstone（不 soft-delete），對稱 episode 層 empty-episodes 守衛、不 throw。**封面快取**：upsert 後 `cacheCoverIfNeeded` 把 `coverImageURL`（有值才）認證下載成 `Documents/podcast-covers/<sid>.png` → 寫 `PodcastSeries.coverImagePath`（PNG-magic 守門、best-effort、失敗退程序化封面、不 abort sync）；**server 撤回封面**（`coverImageURL` 轉 nil/空）時 `upsertSeries` 清掉 `coverImagePath` + best-effort 刪 `<sid>.png`，避免 stale 快取永久渲染；`LocalDataCleanerService.purgePodcastCovers` 於 logout/account-switch 清除。**觸發來源**：BookshelfView `.task`/`.refreshable` + `KGService.backgroundSync`（Phase 3，序執行於 vocab pull 後，見 §同步觸發） |

### 同步觸發

podcast catalog 同步現有兩條觸發鏈：

1. **BookshelfView 局部觸發** — `.task`（每 view identity 跑一次）+ `.refreshable`（下拉，Mac Catalyst 不可用）。
2. **`KGService.backgroundSync` Phase 3**（`KGService+Sync.swift`，序執行於 vocab pull 之後）— 共用所有既有 resync 觸發：post-login / scenePhase→active / ⌘R menu / Settings 手動同步。補上 Catalyst 下「`.refreshable` 不可用、`.task` 僅跑一次」造成書架 podcast 區塊一旦未載入便無路徑復原的缺口（書為本地 `@Query` 故恆在）。token 過期已由 vocab pull 的 401 分支提早 return。

### metadata.json contract

- `episodes[].subtitleContent: String?` 由 `ops/podcast_upload.sh` 嵌入；iOS `PodcastEpisode.inlineSubtitle` 直接消費，跳過 `/api/podcasts/{sid}/{ep}/subtitle` fetch
- `episodes[].localAudioPath: String?` (SwiftData only, 不在後端 JSON) — 由 DownloadManager 填寫；PlayerView 認到即用 file:// URL 跳過認證
- `coverImageURL: String?` 由 `ops/podcast_upload.sh` 寫入（`cover` stage 有產 `cover.png` → `/api/podcasts/{sid}/cover`，否則 `null`）；也在 `index.json` series entry（series list 即可顯示封面）。iOS 有值才拉遠端封面圖快取，否則退 `color`/`coverPattern` 程序化封面

### Sub-views（UI 元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastControlsView.swift` | ~150 | 播放/暫停/快轉/速度控制列（brandHero CTA + appCompactAction；15s ghost 按鈕含 44pt 最小 tap target；seek bar 整條 20pt hit area 可點/拖，幾何換算由 `PodcastSeekBarGeometry` 測試鎖住） |
| `PodcastEpisodeRow.swift` | 130 | 單集 list row（標題、長度、追蹤 chevron），row 節奏 token 對齊 `WordRow` |
| `PodcastSubtitleView.swift` | 55 | 字幕單行渲染 |
| `PodcastSettingsPopover.swift` | ~135 | 字幕大小 S/M/L/XL/XXL + auto-pause toggle + 逐字跟隨 toggle(`@AppStorage("podcast.wordFollowEnabled")`) + 睡眠定時 Picker(off / 5 / 15 / 30 / 60min / endOfEpisode)含 `TimelineView` MM:SS 倒數。**呈現方式**:`PodcastPlayerView` 以 `.sheet`(`NavigationStack` + 完成鈕)叫出，**非** `.popover`——toolbar-anchored `.popover` 在 Mac Catalyst present 過場 trap(`ops/catalyst_lint.sh` 守門)。觸發鈕依 layout 自判:compact 走 `ToolbarItem(.topBarTrailing)`,regular inline 走 `inlineSettingsButton` content overlay(player 不再自帶內層 NavigationStack,見 `PodcastPlayerView` 條目) |
| `PodcastFollowToggle.swift` | 49 | series 追蹤 toggle（已追蹤浮上書庫頂端） |
| `PodcastBadge.swift` | 18 | 「已追蹤」「新集數」狀態 badge |
| `SpeakerAccentBar.swift` | 42 | 多角色播客的口音/語者識別條 |
| `SubtitleRenderState.swift` | 57 | 字幕高亮狀態（current sentence index + 啟動瞬間 layout）|
| `CachedFlowLayout.swift` | 57 | 字幕流式 layout（避免每幀重算） |

### Token Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerMetrics.swift` | ~35 | 播放器 feature-local 尺寸常數 + `PodcastSeekBarGeometry` 純幾何 helper（track position → time / progress width / buffered width） |

---

## 改動規則

- **新增播放器控制 UI** → 抽到 `PodcastControlsView` 或新元件,不要繼續長 `PodcastPlayerView`
- **新增字幕呈現邏輯** → `PodcastSentenceLevelView` 或 `PodcastSubtitleView`,layout 計算抽到 `CachedFlowLayout` 或 `SubtitleRenderState`
- **新增播放狀態（speed / region / queue）** → `PodcastPlayerViewModel`,View 不放 mutable state
- **新增 series / episode 列表 UI** → `PodcastEpisodeListView` + `PodcastEpisodeRow`；列表卡片骨架走共用 `ListSectionCard`（UIComponents，與單字列表共用，見 `docs/reference/ui/components.md` §List Shell），divider 由 caller 在 `ForEach` 內插
- **改 series 層 overlay pane 行為** → `PodcastSeriesActivation`（決策，`PodcastDetailRouter.swift`）+ `BookshelfView` `selectedSeriesRemoteId`；compact 不適用（沿用 push）。**episode → player 已是單欄 push（#672），新增 episode 開啟行為走 `NavigationLink(value: PodcastNavRoute.episode)` + BookshelfView root `navigationDestination`，不要再造 episode 層 inline detail**
- **新增 user-tunable 播放參數(字幕 / 跟隨 / 計時器 等)** → `PodcastSettingsPopover`(集中所有 user-tunable 播放參數;非字幕專屬)
- **新增詞彙互動** → `PodcastVocabularyContext`(reader-parity:任何 reader 詞彙流程都要在此鏡像)
- **新增 metric token** → 跨 feature 用升 `AppMetrics`;單 feature 用留 `PodcastPlayerMetrics`
- **訂閱進度持久化等高頻(15Hz)`@Observable` 狀態** → **絕不**把 `.onChange(of: vm.currentTime)`／類似高頻讀取掛在 `PodcastPlayerView.body`／`playerCore`／`playerContent` 等父層,必須隔離進只渲染 `Color.clear` 的葉子(`PodcastProgressTicker` 模式)。否則 `@Observable` 的 per-view-body 失效會讓父 body 每 tick 重求值、連鎖重建字幕子樹,字幕的 `EquatableView` 優化(`PodcastTranscriptColumn.equatable()`)會被父層 invalidation 架空 → 捲動卡頓 + follow 捲動失效

## State 邊界

- `PodcastPlayerViewModel`：播放器狀態機(playing / current ep / progress / sentence highlight),由 `PodcastPlayerView` 持有,**不**外洩至 series 列表
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

## Storage backend(2026-06 Track B)

- **音頻格式**: AAC/M4A(128k,`+faststart`)。`.mp3` 仍可播,backend `audio.m4a` → `audio.mp3` fallback 涵蓋過渡期 series。
- **位置**: Lightsail Object Storage `s3://kg-podcasts-prod/{series_id}/{metadata.json, cover.png(選), ep_NN/{audio.m4a,subtitle.srt,script.md}}`(`cover.png` 為 series 層封面,`cover` stage 有產才有;舊 disk-mode 路徑 `data/podcasts/...` 仍由 backend 處理,當 `PODCAST_BUCKET` env 未設時)。
- **iOS 變更**: 零。`AVURLAssetHTTPHeaderFields` 帶 `Authorization: Bearer`,backend 走 proxy 模式(不 302 redirect 到 presigned URL,避免 AWS sig + Bearer header 衝突 → 403)。
- **Range 支援**: backend 把 `Range` header 原樣轉給 S3 `get_object(Range=...)`,S3 回 206 + `Content-Range`,backend 透傳。
- **過渡期回退**: `PODCAST_BUCKET` env unset → backend 改走 disk fallback,舊 series 仍可播。
- 詳見 `docs/sop/podcast_pipeline.md §Storage`。

## 架構債

- **podcast 無頂層 section、被迫經 `BookshelfView` 進入。** podcast 沒有頂層 section，regular 下靠 `BookshelfView` 的 `@State selectedSeriesRemoteId` 把 series 集數列表作為疊加在恒定 root content 上的 overlay master pane（非 root-content swap）取得 reader push 免疫。**2026-06 #672 後 episode → player 已收斂為單欄 push**，此 overlay 僅剩集數列表單一窗格（不再含右欄 inline player + `safeAreaInset` 假兩欄）。series 層仍是 overlay pane 而非平台原生 `NavigationSplitView`——未來可評估以原生 split 收斂 series master pane，但需先驗證 Catalyst 巢狀 split（`ContentView` 已用 `NavigationSplitView`）穩定性，本輪不做。

## 相關 doc

- `docs/reference/feature_boundary/reader.md` — reader 翻譯流程,podcast `VocabularyContext` 必須 mirror
- `docs/reference/sync_lifecycle.md` — 詞彙加入後的 sync 規則(**SoT**)
- `docs/sop/backend.md` — `/api/podcasts*` endpoint 與 progress LWW 後端細節
- `docs/sop/podcast_pipeline.md` — pipeline(synthesize → upload → S3)
- `docs/reference/product_surface.md` §Podcast player — 已實作功能清冊(避免重做)
