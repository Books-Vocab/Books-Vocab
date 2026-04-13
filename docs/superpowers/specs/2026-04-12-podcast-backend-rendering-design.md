# Podcast 後端資產管理 + iOS 渲染重構 — Design Spec

## 概覽

將 podcast 內容（MP3/SRT/腳本）從 iOS bundle debug 資源遷移至後端全域儲存，建立 API 供 iOS 拉取；同時重構 iOS 字幕渲染管線，將高頻變化（word highlight）與低頻變化（sentence 切換）分離，消除每幀重建。

## 設計決策

| 決策 | 選擇 | 理由 |
|------|------|------|
| 內容儲存位置 | 後端 `/data/podcasts/`（全域共享） | podcast 內容不分使用者，與 per-user vocab 本質不同 |
| 播放進度同步 | iOS CloudKit（與 Book 一致） | 裝置間同步，零後端成本，離線友好 |
| 渲染優化策略 | 重構渲染管線（方向 B） | 從根本拆分高/低頻狀態，非補丁式 |
| 上傳工作流 | ops rsync 腳本 | 低頻操作，與現有部署工具一致 |

---

## 一、後端：Podcast 資產服務

### 1.1 儲存結構

```
/data/podcasts/                          ← docker volume, 與 /data/users 同級
  index.json                             ← 系列索引（所有 series 的 metadata）
  flow_950f1a7d/
    metadata.json                        ← 單一系列 metadata
    ep_01/
      audio.mp3
      subtitle.srt
      script.md                          ← 可選，供未來 reference
    ep_02/
      audio.mp3
      subtitle.srt
  atomic_habits_033e3990/
    metadata.json
    ep_01/
      ...
```

### 1.2 metadata.json 格式

```json
{
  "id": "flow_950f1a7d",
  "title": "Flow: The Psychology of Optimal Experience",
  "author": "Mihaly Csikszentmihalyi",
  "hostNames": ["Maya", "Kai"],
  "color": "#5B8C5A",
  "coverPattern": "waves",
  "totalDurationSec": 11700,
  "episodes": [
    {
      "episodeNumber": 1,
      "title": "The Happiness Trap",
      "durationSec": 1420,
      "audioAvailable": true,
      "subtitleAvailable": true
    }
  ],
  "createdAt": "2026-04-12T20:00:00Z",
  "updatedAt": "2026-04-12T21:30:00Z"
}
```

`index.json` = `metadata.json` 的陣列（不含 episodes 明細，只含 series 級摘要 + episodeCount）。

### 1.3 API Endpoints

新增 `backend/src/kg/routers/podcast.py`：

| Method | Path | Auth | 回應 | 說明 |
|--------|------|------|------|------|
| GET | `/api/podcasts` | 不需 | JSON array（series 摘要） | 從 `index.json` 讀取 |
| GET | `/api/podcasts/{series_id}` | 不需 | JSON（series 完整 metadata） | 從 `{series_id}/metadata.json` 讀取 |
| GET | `/api/podcasts/{series_id}/{ep_num}/subtitle` | 不需 | PlainTextResponse (SRT) | 返回 `ep_{num}/subtitle.srt` 文字內容 |
| mount | `/api/podcast-media/` | 不需 | StaticFiles | 音訊靜態檔案（Range + ETag） |

**音訊 URL**：`/api/podcast-media/{series_id}/ep_{num}/audio.mp3`（由 StaticFiles 直接 serve，不經 router）

**設計要點**：
- 不需 auth — podcast 是公開內容（未來可加 series-level 付費 gate）
- 音訊用獨立的 `StaticFiles` mount（`FileResponse` 不支援 Range request；`StaticFiles` 內建 Range + ETag + Content-Length）。Mount 在 `/api/podcast-media/` 而非 `/api/podcasts/static/` 以避免與 JSON endpoints 混淆
- **StaticFiles 安全性**：mount directory 只指向 podcasts 根目錄，metadata.json / index.json / script.md 也會被暴露。可接受——這些本身就是公開內容。iOS 端只拼接音訊 URL，不走 static 拿 metadata
- 所有 JSON 端點從檔案系統直讀，不需 DB
- 路徑驗證：JSON endpoints reject `..` 和任何非 `[a-z0-9_]` 的 series_id

**Router 註冊**：加入 `api.py` 的 `app.include_router(podcast_router)` （參考 `api.py:303-312`）

### 1.4 Docker Volume 掛載

`docker-compose.yml` 新增：
```yaml
volumes:
  - ./data:/app/data          # 現有
  # /data/podcasts/ 在 /app/data/podcasts/ — 不需額外 mount
```

Podcast 目錄在 `/app/data/podcasts/`，由 `KGSettings.data_dir / "podcasts"` 解析，不需額外 volume。

### 1.5 Settings 擴充

`settings.py` 新增：
```python
@property
def podcasts_dir(self) -> Path:
    return self.data_dir / "podcasts"
```

---

## 二、Ops：上傳管理

### 2.1 podcast_upload.sh

```bash
# 用法：
./ops/podcast_upload.sh <workspace_path> [series_id]

# 範例：
./ops/podcast_upload.sh lab/podcast/workspaces/flow_950f1a7d/
./ops/podcast_upload.sh lab/podcast/workspaces/atomic_habits_033e3990/ atomic_habits
```

**行為**：
1. 從 workspace `plan/overview.md` 萃取 metadata → 生成 `metadata.json`
2. 將 `scripts/ep_*_pro.mp3` 重命名為 `ep_NN/audio.mp3`
3. 將 `scripts/ep_*_pro.srt` 重命名為 `ep_NN/subtitle.srt`
4. 將 `scripts/ep_*_script.md` 複製為 `ep_NN/script.md`
5. rsync 至 server `/data/podcasts/{series_id}/`
6. 重建 `index.json`（遠端執行，掃描所有 series metadata）

### 2.2 metadata 萃取

從 `plan/overview.md` 解析：
- 標題、作者 → 從 header + book analysis
- hostNames → 從 Host A/B sections
- episode map → 從 Episode Map table
- duration → 從 mp3 檔案 metadata（ffprobe）

---

## 三、iOS：Model 層調整

### 3.1 PodcastSeries / PodcastEpisode 保留在 LocalStore

這兩個 model 是後端資料的本地快取，不需 CloudKit 同步：
- 從 API 拉取後寫入 SwiftData
- 保留現有 `remoteId` 欄位作為後端 ID

### 3.2 新增 PodcastProgress model → CloudStore

```swift
@Model
final class PodcastProgress {
    @Attribute(.unique) var episodeRemoteId: String = ""  // 格式與 PodcastEpisode.remoteId 完全一致
    var lastPlayedTime: Double = 0         // 秒
    var completed: Bool = false
    var updatedAt: Date = Date()
}
```

**`episodeRemoteId` 格式約定**：`"{series_id}_ep_{zero_padded_num}"`，例如 `"flow_950f1a7d_ep_01"`。必須與 `PodcastEpisode.remoteId`（從後端 metadata 同步而來）完全一致。取代舊的 debug 格式（`"debug-flow-ep1"`）。由 `PodcastSyncService` 寫入 episode 時統一生成。

**Schema 變更**（`BooksBrowserApp.swift`）：

`cloudConfig` 在建構處只改一次，`retryAfterStoreReset` 複用同一個 config 物件不需重複改。但以下位置也引用了 model type 列表，必須全部加入 `PodcastProgress.self`：

```swift
// 1. cloudConfig schema（L52-54）— 改這一處，retry 複用同一個 config
let cloudConfig = ModelConfiguration(
    "CloudStore",
    schema: Schema([Book.self, PodcastProgress.self]),  // ← 新增
    cloudKitDatabase: .automatic
)

// 2. allModels 陣列（L57）— 用於 debug logging
// 3. 主 ModelContainer(for:) 的 type 列表（L60-61）
// 4. retryAfterStoreReset 中 localOnlyConfig 的 schema（L326-332）— fallback 只用 local 不走 CloudKit，但仍需知道所有 model types
// 5. makeFallbackModelContainer 的 type 列表（L339-340）
```

### 3.3 PodcastEpisode model 調整

```swift
// 移除 bundle fallback 邏輯，改為純後端 URL
var audioURL: String?           // → "https://wordnexus.lol/api/podcasts/{series}/{ep}/audio"
var subtitleURL: String?        // → "https://wordnexus.lol/api/podcasts/{series}/{ep}/subtitle"

// localAudioPath / localSubtitlePath 保留（未來離線下載用，目前不實作）
```

### 3.4 移除 PodcastDebugSeed

`PodcastDebugSeed.swift` 和 `BooksBrowserApp.swift` 中的 `seedIfNeeded()` 呼叫一併移除。`Resources/debug_podcast.mp3` 和 `debug_podcast.srt` 從 bundle 移除。

### 3.5 新增 PodcastSyncService

負責從後端拉取 series/episode metadata 並同步到 LocalStore：

```swift
final class PodcastSyncService {
    func fetchSeriesList() async throws -> [PodcastSeriesResponse]
    func fetchSeriesDetail(seriesId: String) async throws -> PodcastSeriesDetailResponse
    func syncAll(context: ModelContext) async throws   // 全量同步
}
```

呼叫時機：app launch + bookshelf pull-to-refresh。

---

## 四、iOS：渲染管線重構

### 4.1 核心理念：分離高頻與低頻狀態

```
高頻（60Hz display link）         低頻（sentence 切換，~0.2Hz）
─────────────────────────         ──────────────────────────────
highlightedWordIndex: Int         currentSentence: PodcastSentence
                                  precomputedWords: [WordRenderItem]
                                  speakerColor: Color
```

**關鍵**：`highlightedWordIndex` 變化時不觸發 sentence 容器重繪。

### 4.2 SubtitleRenderState（預計算結構）

```swift
struct WordRenderItem: Identifiable, Equatable {
    let id: Int              // word index
    let text: String
    let normalizedText: String    // lowercased + punctuation trimmed，用於 highlight 匹配
    let isHighlightTarget: Bool   // 這�� word 是否有對應的 cue highlight
}

struct SubtitleRenderState: Equatable {
    let sentenceId: Int
    let speaker: String
    let speakerColor: Color
    let words: [WordRenderItem]

    // 只在 sentence 切換時重建，不在 word highlight 變化時重建
}
```

ViewModel 在 `currentSentence` 變化時生成 `SubtitleRenderState`，word array 只計算一次。

### 4.3 ViewModel 變更

```swift
@MainActor @Observable
final class PodcastPlayerViewModel {
    // 低頻狀態（sentence 切換時更新）
    private(set) var renderState: SubtitleRenderState?
    private(set) var sentences: [PodcastSentence]         // 全部，用於 sentence-level view

    // 高頻狀態（每幀更新，但隔離）
    private(set) var highlightedWordIndex: Int = -1        // 當前亮的 word 在 renderState.words 中的 index
    private(set) var currentTime: TimeInterval = 0

    // Display link 回調
    func handleTimeUpdate(_ time: TimeInterval) {
        currentTime = time
        let newCue = subtitleEngine.currentCue(at: time)

        // 高頻路徑：只更新 index
        // 注意：匹配邏輯需 case-insensitive + 標點 trim，因為 SRT cue 的
        // highlightedWord 和 split 出來的 word 可能大小寫/標點不同
        if let cue = newCue, let highlightWord = cue.highlightedWord, let rs = renderState {
            let normalized = highlightWord.lowercased().trimmingCharacters(in: .punctuationCharacters)
            let newIndex = rs.words.firstIndex { $0.normalizedText == normalized } ?? -1
            if newIndex != highlightedWordIndex {
                highlightedWordIndex = newIndex
            }
        }

        // 低頻路徑：sentence 切換時才重建 renderState
        let newSentence = subtitleEngine.currentSentence(at: time)
        if newSentence?.id != renderState?.sentenceId {
            rebuildRenderState(for: newSentence)
        }
    }
}
```

### 4.4 Display Link 降頻

`PodcastAudioEngine` 中：
```swift
// preferredFramesPerSecond 已 deprecated，用 preferredFrameRateRange
displayLink?.preferredFrameRateRange = CAFrameRateRange(minimum: 15, maximum: 30, preferred: 30)
```

### 4.5 WordLevelView 重構

```swift
struct PodcastWordLevelView: View {
    let renderState: SubtitleRenderState       // 低頻，sentence 切換時才變
    let highlightedWordIndex: Int              // 高頻，但只是一個 Int
    let onWordTap: (String, String) -> Void

    // body 不再做 split/map/search
    // words 來自預計算的 renderState.words
    // highlight 判斷 = index 比較（O(1)）
}
```

**Equatable 隔離**：`renderState` 不變時，SwiftUI diff 只比較 `highlightedWordIndex`，不重走 word layout。

### 4.6 SentenceLevelView 優化

- 視窗化：只渲染 `currentIndex ± 10` 的 sentences
- `currentSentence` binary search（改 `PodcastSubtitleEngine.currentSentence`）
- ScrollViewReader 加 debounce（避免每幀觸發 scroll）

### 4.7 FlowLayout 修復

快取 layout 計算結果，只在 `renderState` 變化（= sentence 切換）時重算：
```swift
struct CachedFlowLayout: Layout {
    // sizeThatFits 計算一次，placeSubviews 複用結果
    // 用 cache 參數（Layout protocol 內建）
}
```

### 4.8 Translation Debounce

`PodcastTranslationHandler` 加 300ms debounce：
```swift
func handleWordTap(word: String, context: String) {
    pendingTask?.cancel()
    pendingTask = Task {
        try await Task.sleep(for: .milliseconds(300))
        // ... 實際翻譯
    }
}
```

---

## 五、數據流總覽

```
lab/podcast/pipeline.py
    ↓ 產出 MP3 + SRT + script
ops/podcast_upload.sh
    ↓ rsync 至 server
Backend /data/podcasts/
    ↓ GET /api/podcasts/* (JSON) + /api/podcast-media/* (StaticFiles)
iOS PodcastSyncService
    ↓ fetchSeriesList → SwiftData LocalStore
    ↓ audio/subtitle URL 指向後端
iOS PodcastPlayerView
    ↓ AVAudioEngine 載入後端 audio URL
    ↓ PodcastSubtitleEngine 解析後端 SRT
    ↓ PodcastPlayerViewModel 預計算 SubtitleRenderState
    ↓ Display link 30fps → 只更新 highlightedWordIndex
    ↓ PodcastWordLevelView/SentenceLevelView 渲染
    ↓ PodcastProgress → CloudKit 同步
```

---

## 六、不做的事（YAGNI）

| 不做 | 理由 |
|------|------|
| 離線下載管理 | MVP 只需串流；離線是後續 feature |
| 背景播放 / MPNowPlayingInfoCenter | 獨立 feature，不在此 scope |
| Mini player | 獨立 feature |
| 付費解鎖 / per-series gate | 目前只有你用 |
| Admin dashboard podcast 管理 | ops 腳本夠用 |
| Backend DB（SQLite for podcast） | 純 JSON + 檔案系統，無需 ORM |

---

## 七、風險與緩解

| 風險 | 緩解 |
|------|------|
| AVAudioEngine 不支援 HTTP Range streaming | 用 AVPlayer 替代，或先下載到 tmp 再播放 |
| 24MB MP3 首次載入慢 | 加 loading progress indicator |
| CloudKit PodcastProgress schema 變更 | 用簡單扁平結構，避免 migration |
| SRT 解析後端格式與 debug 格式不一致 | 上傳腳本統一格式驗證 |
