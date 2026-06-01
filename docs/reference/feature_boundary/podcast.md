<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Podcast/
verified_against: 226c306c
-->
# Podcast Feature Boundary

## 檔案清冊

### Container Layer（主場景 View）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerView.swift` | ~590 | 主播放器容器 `struct PodcastPlayerView: View`，audio + 字幕同步 + 翻譯面板 + 控制列。`wrapInNavigation: Bool = false` 參數：預設 false → push caller（BookshelfView `navigationDestination`）沿用父 `NavigationStack`；雙欄右欄 inline 嵌入傳 true → 自帶 `NavigationStack` host 住設定 `ToolbarItem(.topBarTrailing)`（`.topBarTrailing` 需 ambient nav bar）。啟動期透過 `PodcastPlayerBootstrapPhase` 區分未嘗試載入、已嘗試但 SwiftData 缺 episode/series、播放器 ready，避免 missing local row 時永久 spinner |
| `PodcastEpisodeListView.swift` | ~450 | 單集列表 + series 詳情容器 `struct PodcastEpisodeListView: View`。Mac/iPad regular 走左右雙欄（左集數列表常駐 + 右欄 inline player，點集數或頂部開始/繼續播放 CTA 即時 swap，選中 row 染 `accentSubtle`，靠 `detailRouter.show` 不 push）；iPhone compact 沿用 value-based `NavigationLink push`（freeze-fix 契約，見檔頭註解）。分支以 `PodcastEpisodeActivation.activation(..., layoutMode:)` 集中切換 |
| `PodcastSentenceLevelView.swift` | ~390 | 句級字幕 + 長按整句翻譯 + 點詞查詞 + follow-mode pill `struct PodcastSentenceLevelView: View`（iPhone/iPad：拖曳隱式脫離 follow，pill 僅在脫離時顯示；Mac Catalyst：滑鼠滾輪/觸控板 indirect scroll 不觸發 DragGesture，pill 常駐為明確 toggle「停止跟隨 ⇄ 追隨當前」，邏輯在 `shouldShowFollowControl`） |

### Master-Detail Layer（Mac/iPad 雙欄）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastDetailRouter.swift` | ~45 | `@Observable` 集數 master-detail 狀態（`selectedEpisodeRemoteId` / `show` / `dismiss` / `hasDetail`），鏡射 vocab/notebook detail router；同檔 `PodcastEpisodeActivation` 是 compact push vs regular inline detail 的單一決策點。透過 `\.podcastDetailRouter` environment 注入。compact 下右欄不掛，`selectedEpisodeRemoteId` 恆 nil |
| `PodcastDetailPresentation.swift` | 74 | `struct PodcastDetailPresentation: ViewModifier`（`.podcastDetailPresentation(router:layoutMode:)`），鏡射 `NotebookDetailPresentation`。inline mode（iPad/Mac regular）右側 `safeAreaInset(edge:.trailing)` 掛可拖拉 panel（複用 `DraggableDivider` + `@AppStorage("kg_podcast_panel_width")` + `MacDetailPanelMetrics`），單一 `PodcastPlayerView(wrapInNavigation:true)` 靠 `.task(id:)` swap 集數；compact 不掛右欄。`layoutMode` 退出 inline 時 `router.dismiss()` |

### ViewModel Layer（播放狀態機）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerViewModel.swift` | ~375 | `@Observable @MainActor final class PodcastPlayerViewModel`,播放/暫停/seek + auto-pause-on-lookup + per-user progress LWW sync + sleep timer(`sleepTimerMode` / `sleepDeadline` / `DispatchSourceTimer` wall-clock;`.endOfEpisode` 由 audio engine load 換集 callback reset) + `bufferedEnd`(YouTube-style buffer overlay) + `subtitleState: PodcastSubtitleLoadState`(idle/loading/loaded/failed + inline retry) + `PodcastPlayerBootstrapPhase`(播放器啟動期 loading / missingEpisode / ready 分類) + `onSystemPause` / `onSystemResume` interruption hooks + `prefetchedDurationSec` + `audioHTTPHeaders` 透傳 + `stop()`(session-internal teardown) vs `shutdown()`(terminal cleanup) |

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
| `PodcastSyncService.swift` | @MainActor；`syncAll(context:)` 拉取後端 podcast catalog 並 upsert series/episode。**自我防禦**：list fetch 失敗即 skip、空 server list（`/api/podcasts` 回 `[]`，S3 index.json 短暫讀不到時）視為非權威 → reconcile 跳過 series tombstone（不 soft-delete），對稱 episode 層 empty-episodes 守衛、不 throw。**觸發來源**：BookshelfView `.task`/`.refreshable` + `KGService.backgroundSync`（Phase 3，序執行於 vocab pull 後，見 §同步觸發） |

### 同步觸發

podcast catalog 同步現有兩條觸發鏈：

1. **BookshelfView 局部觸發** — `.task`（每 view identity 跑一次）+ `.refreshable`（下拉，Mac Catalyst 不可用）。
2. **`KGService.backgroundSync` Phase 3**（`KGService+Sync.swift`，序執行於 vocab pull 之後）— 共用所有既有 resync 觸發：post-login / scenePhase→active / ⌘R menu / Settings 手動同步。補上 Catalyst 下「`.refreshable` 不可用、`.task` 僅跑一次」造成書架 podcast 區塊一旦未載入便無路徑復原的缺口（書為本地 `@Query` 故恆在）。token 過期已由 vocab pull 的 401 分支提早 return。

### metadata.json contract

- `episodes[].subtitleContent: String?` 由 `ops/podcast_upload.sh` 嵌入；iOS `PodcastEpisode.inlineSubtitle` 直接消費，跳過 `/api/podcasts/{sid}/{ep}/subtitle` fetch
- `episodes[].localAudioPath: String?` (SwiftData only, 不在後端 JSON) — 由 DownloadManager 填寫；PlayerView 認到即用 file:// URL 跳過認證

### Sub-views（UI 元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastControlsView.swift` | 148 | 播放/暫停/快轉/速度控制列（brandHero CTA + appCompactAction；15s ghost 按鈕含 44pt 最小 tap target） |
| `PodcastEpisodeRow.swift` | 130 | 單集 list row（標題、長度、追蹤 chevron），row 節奏 token 對齊 `WordRow` |
| `PodcastSubtitleView.swift` | 55 | 字幕單行渲染 |
| `PodcastSettingsPopover.swift` | ~135 | 字幕大小 S/M/L/XL/XXL + auto-pause toggle + 逐字跟隨 toggle(`@AppStorage("podcast.wordFollowEnabled")`) + 睡眠定時 Picker(off / 5 / 15 / 30 / 60min / endOfEpisode)含 `TimelineView` MM:SS 倒數。**呈現方式**:`PodcastPlayerView` 從 ToolbarItem 以 `.sheet`(`NavigationStack` + 完成鈕)叫出，**非** `.popover`——toolbar-anchored `.popover` 在 Mac Catalyst present 過場 trap(`ops/catalyst_lint.sh` 守門) |
| `PodcastFollowToggle.swift` | 49 | series 追蹤 toggle（已追蹤浮上書庫頂端） |
| `PodcastBadge.swift` | 18 | 「已追蹤」「新集數」狀態 badge |
| `SpeakerAccentBar.swift` | 42 | 多角色播客的口音/語者識別條 |
| `SubtitleRenderState.swift` | 57 | 字幕高亮狀態（current sentence index + 啟動瞬間 layout）|
| `CachedFlowLayout.swift` | 57 | 字幕流式 layout（避免每幀重算） |

### Token Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerMetrics.swift` | 11 | 播放器 feature-local 尺寸常數 |

---

## 改動規則

- **新增播放器控制 UI** → 抽到 `PodcastControlsView` 或新元件,不要繼續長 `PodcastPlayerView`
- **新增字幕呈現邏輯** → `PodcastSentenceLevelView` 或 `PodcastSubtitleView`,layout 計算抽到 `CachedFlowLayout` 或 `SubtitleRenderState`
- **新增播放狀態（speed / region / queue）** → `PodcastPlayerViewModel`,View 不放 mutable state
- **新增 series / episode 列表 UI** → `PodcastEpisodeListView` + `PodcastEpisodeRow`；列表卡片骨架走共用 `ListSectionCard`（UIComponents，與單字列表共用，見 `docs/reference/ui/components.md` §List Shell），divider 由 caller 在 `ForEach` 內插
- **新增雙欄 master-detail 行為** → `PodcastDetailRouter`（狀態）+ `PodcastDetailPresentation`（呈現分支）；compact 不適用（沿用 push）
- **新增 user-tunable 播放參數(字幕 / 跟隨 / 計時器 等)** → `PodcastSettingsPopover`(集中所有 user-tunable 播放參數;非字幕專屬)
- **新增詞彙互動** → `PodcastVocabularyContext`(reader-parity:任何 reader 詞彙流程都要在此鏡像)
- **新增 metric token** → 跨 feature 用升 `AppMetrics`;單 feature 用留 `PodcastPlayerMetrics`

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
- **位置**: Lightsail Object Storage `s3://kg-podcasts-prod/{series_id}/ep_NN/{audio.m4a,subtitle.srt,script.md,metadata.json}`(舊 disk-mode 路徑 `data/podcasts/...` 仍由 backend 處理,當 `PODCAST_BUCKET` env 未設時)。
- **iOS 變更**: 零。`AVURLAssetHTTPHeaderFields` 帶 `Authorization: Bearer`,backend 走 proxy 模式(不 302 redirect 到 presigned URL,避免 AWS sig + Bearer header 衝突 → 403)。
- **Range 支援**: backend 把 `Range` header 原樣轉給 S3 `get_object(Range=...)`,S3 回 206 + `Content-Range`,backend 透傳。
- **過渡期回退**: `PODCAST_BUCKET` env unset → backend 改走 disk fallback,舊 series 仍可播。
- 詳見 `docs/sop/podcast_pipeline.md §Storage`。

## 相關 doc

- `docs/reference/feature_boundary/reader.md` — reader 翻譯流程,podcast `VocabularyContext` 必須 mirror
- `docs/reference/sync_lifecycle.md` — 詞彙加入後的 sync 規則(**SoT**)
- `docs/sop/backend.md` — `/api/podcasts*` endpoint 與 progress LWW 後端細節
- `docs/sop/podcast_pipeline.md` — pipeline(synthesize → upload → S3)
- `docs/reference/product_surface.md` §Podcast player — 已實作功能清冊(避免重做)
