<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Podcast/
verified_against: c642ed18
-->
# Podcast Feature Boundary

## 檔案清冊

### Container Layer（主場景 View）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerView.swift` | ~560 | 主播放器容器 `struct PodcastPlayerView: View`，audio + 字幕同步 + 翻譯面板 + 控制列 |
| `PodcastEpisodeListView.swift` | ~410 | 單集列表 + series 詳情容器 `struct PodcastEpisodeListView: View` |
| `PodcastSentenceLevelView.swift` | ~390 | 句級字幕 + 長按整句翻譯 + 點詞查詞 `struct PodcastSentenceLevelView: View` |

### ViewModel Layer（播放狀態機）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastPlayerViewModel.swift` | ~355 | `@Observable @MainActor final class PodcastPlayerViewModel`,播放/暫停/seek + auto-pause-on-lookup + per-user progress LWW sync + sleep timer(`sleepTimerMode` / `sleepDeadline` / `DispatchSourceTimer` wall-clock;`.endOfEpisode` 由 audio engine load 換集 callback reset) + `bufferedEnd`(YouTube-style buffer overlay) + `subtitleState: PodcastSubtitleLoadState`(idle/loading/loaded/failed + inline retry) + `onSystemPause` / `onSystemResume` interruption hooks + `prefetchedDurationSec` + `audioHTTPHeaders` 透傳 + `stop()`(session-internal teardown) vs `shutdown()`(terminal cleanup) |

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

### metadata.json contract

- `episodes[].subtitleContent: String?` 由 `ops/podcast_upload.sh` 嵌入；iOS `PodcastEpisode.inlineSubtitle` 直接消費，跳過 `/api/podcasts/{sid}/{ep}/subtitle` fetch
- `episodes[].localAudioPath: String?` (SwiftData only, 不在後端 JSON) — 由 DownloadManager 填寫；PlayerView 認到即用 file:// URL 跳過認證

### Sub-views（UI 元件）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `PodcastControlsView.swift` | 115 | 播放/暫停/快轉/速度控制列 |
| `PodcastEpisodeRow.swift` | 130 | 單集 list row（標題、長度、追蹤 chevron） |
| `PodcastSubtitleView.swift` | 55 | 字幕單行渲染 |
| `PodcastSettingsPopover.swift` | ~135 | 字幕大小 S/M/L/XL/XXL + auto-pause toggle + 逐字跟隨 toggle(`@AppStorage("podcast.wordFollowEnabled")`) + 睡眠定時 Picker(off / 5 / 15 / 30 / 60min / endOfEpisode)含 `TimelineView` MM:SS 倒數 |
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
- **新增 series / episode 列表 UI** → `PodcastEpisodeListView` + `PodcastEpisodeRow`
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

## 相關 doc

- `docs/reference/feature_boundary/reader.md` — reader 翻譯流程,podcast `VocabularyContext` 必須 mirror
- `docs/reference/sync_lifecycle.md` — 詞彙加入後的 sync 規則(**SoT**)
- `docs/sop/backend.md` — `/api/podcasts*` endpoint 與 progress LWW 後端細節
- `docs/reference/product_surface.md` §Podcast player — 已實作功能清冊(避免重做)
