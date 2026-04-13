# Podcast 後端資產管理 + iOS 渲染重構 Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 將 podcast 資產遷移至後端全域儲存，iOS 改為後端拉取 + 渲染管線重構
**Architecture:** 後端 JSON + StaticFiles 服務（無 DB）；iOS CloudKit 進度同步；渲染管線分離高/低頻狀態
**Tech Stack:** FastAPI StaticFiles, SwiftData CloudKit, AVAudioEngine, CADisplayLink

**Spec:** `docs/superpowers/specs/2026-04-12-podcast-backend-rendering-design.md`

---

## Task 1: Backend — Podcast API + StaticFiles Mount

**Files:**
- Create: `backend/src/kg/routers/podcast.py`
- Modify: `backend/src/kg/settings.py:53-59`
- Modify: `backend/src/kg/api.py:302-312`
- Test: `backend/tests/test_podcast_api.py`

- [ ] **Step 1: 寫 failing test**
```python
# backend/tests/test_podcast_api.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

@pytest.fixture
def podcast_dir(tmp_path):
    """Create a tmp podcasts directory and monkeypatch settings to use it."""
    d = tmp_path / "podcasts"
    d.mkdir()
    return d

@pytest.fixture
def podcast_client(podcast_dir):
    """TestClient with podcasts_dir overridden to tmp_path."""
    # monkeypatch the router's _podcasts_dir to return our tmp dir
    with patch("kg.routers.podcast._podcasts_dir", return_value=podcast_dir):
        from kg.api import create_app
        app = create_app()
        yield TestClient(app)

def test_podcasts_list_returns_index(podcast_client, podcast_dir):
    """GET /api/podcasts returns series list from index.json."""
    (podcast_dir / "index.json").write_text('[{"id":"test_abc","title":"Test","episodeCount":1}]')
    resp = podcast_client.get("/api/podcasts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "test_abc"

def test_podcasts_list_empty_when_no_index(podcast_client):
    resp = podcast_client.get("/api/podcasts")
    assert resp.status_code == 200
    assert resp.json() == []

def test_podcasts_series_detail(podcast_client, podcast_dir):
    """GET /api/podcasts/{series_id} returns metadata.json."""
    series_dir = podcast_dir / "test_abc"
    series_dir.mkdir()
    (series_dir / "metadata.json").write_text('{"id":"test_abc","title":"Test","episodes":[]}')
    resp = podcast_client.get("/api/podcasts/test_abc")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test"

def test_podcasts_series_not_found(podcast_client):
    resp = podcast_client.get("/api/podcasts/nonexistent")
    assert resp.status_code == 404

def test_podcasts_series_id_rejects_traversal(podcast_client):
    resp = podcast_client.get("/api/podcasts/../etc/passwd")
    assert resp.status_code in (404, 422)

def test_podcast_subtitle_endpoint(podcast_client, podcast_dir):
    """GET /api/podcasts/{series}/{ep}/subtitle returns SRT content."""
    ep_dir = podcast_dir / "test_abc" / "ep_01"
    ep_dir.mkdir(parents=True)
    (ep_dir / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n[Maya] Hello\n")
    resp = podcast_client.get("/api/podcasts/test_abc/1/subtitle")
    assert resp.status_code == 200
    assert "[Maya] Hello" in resp.text
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && uv run pytest tests/test_podcast_api.py -v`
Expected: FAIL (no podcast router)

- [ ] **Step 3: 寫 settings.py 擴充**
在 `settings.py:59` 後新增：
```python
@property
def podcasts_dir(self) -> Path:
    return self.data_dir / "podcasts"
```

- [ ] **Step 4: 寫 podcast router**
建立 `backend/src/kg/routers/podcast.py`：
```python
import json
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from ..settings import get_settings

router = APIRouter(tags=["podcast"])
_SERIES_ID_RE = re.compile(r"^[a-z0-9_]+$")

def _podcasts_dir() -> Path:
    return get_settings().podcasts_dir

@router.get("/api/podcasts")
def list_podcasts():
    index_file = _podcasts_dir() / "index.json"
    if not index_file.exists():
        return []
    return json.loads(index_file.read_text(encoding="utf-8"))

@router.get("/api/podcasts/{series_id}")
def get_podcast_series(series_id: str):
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    meta_file = _podcasts_dir() / series_id / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(404, detail="Series not found")
    return json.loads(meta_file.read_text(encoding="utf-8"))

@router.get("/api/podcasts/{series_id}/{ep_num}/subtitle")
def get_podcast_subtitle(series_id: str, ep_num: int):
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    srt_file = _podcasts_dir() / series_id / f"ep_{ep_num:02d}" / "subtitle.srt"
    if not srt_file.exists():
        raise HTTPException(404, detail="Subtitle not found")
    return PlainTextResponse(srt_file.read_text(encoding="utf-8"))
```

- [ ] **Step 5: 註冊 router + StaticFiles mount**
在 `api.py` 中，**所有 `include_router` 之後**（包含 admin router）加入：
```python
from .routers.podcast import router as podcast_router
app.include_router(podcast_router)

# StaticFiles mount 必須在所有 router 之後，避免 path shadow
from starlette.staticfiles import StaticFiles
_podcasts_dir = get_settings().podcasts_dir
if _podcasts_dir.exists():
    app.mount("/api/podcast-media", StaticFiles(directory=str(_podcasts_dir)), name="podcast-media")
```
**注意**：`app.mount()` 是 catch-all，若放在 router 之前會 shadow 同 prefix 的路由。放在最末尾。

- [ ] **Step 7: 跑 test 確認通過**
Run: `cd backend && uv run pytest tests/test_podcast_api.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**
`api: add podcast API — series list, detail, subtitle + StaticFiles mount`

---

## Task 2: Ops — podcast_upload.sh

**Files:**
- Create: `ops/podcast_upload.sh`

- [ ] **Step 1: 寫上傳腳本**
```bash
#!/usr/bin/env bash
# Upload podcast workspace assets to server
# Usage: ./ops/podcast_upload.sh <workspace_path> [series_id_override]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/devops.sh" _source_only  # 取得 SSH_KEY, SERVER, REMOTE_DIR 等變數
```

核心邏輯：
1. 驗證 workspace 存在且有 `plan/overview.md`
2. 從 workspace name 萃取 series_id（或用 override）
3. 建立本地 staging dir，整理檔案結構：
   - `scripts/ep_N_pro.mp3` → `ep_NN/audio.mp3`
   - `scripts/ep_N_pro.srt` → `ep_NN/subtitle.srt`
   - `scripts/ep_N_script.md` → `ep_NN/script.md`
4. 用 Python 從 `plan/overview.md` 萃取 metadata → 生成 `metadata.json`
   - ffprobe 取得每集 duration（若 mp3 存在）
5. rsync staging dir 至 `server:~/knowledge_graph_api/data/podcasts/{series_id}/`
6. 遠端重建 `index.json`（掃描所有 `*/metadata.json`，去除 episodes 明細，聚合為陣列）

- [ ] **Step 2: 本地 dry-run 測試**
Run: `./ops/podcast_upload.sh lab/podcast/workspaces/flow_950f1a7d/ --dry-run`
驗證 staging dir 結構正確

- [ ] **Step 3: Commit**
`ops: add podcast_upload.sh — workspace assets → server rsync`

---

## Task 3: iOS — Model 層調整 + PodcastProgress CloudKit

**Files:**
- Create: `ios/BooksBrowser/Models/PodcastProgress.swift`
- Modify: `ios/BooksBrowser/BooksBrowserApp.swift:45-63, 317-345`
- Modify: `ios/BooksBrowser/Models/PodcastEpisode.swift`
- Delete: `ios/BooksBrowser/Services/PodcastDebugSeed.swift`
- Delete: `ios/BooksBrowser/Resources/debug_podcast.mp3`
- Delete: `ios/BooksBrowser/Resources/debug_podcast.srt`
- Modify: `ios/BooksBrowser.xcodeproj/project.pbxproj`（移除 debug 資源引用）
- Test: `ios/BooksBrowserTests/PodcastProgressTests.swift`

- [ ] **Step 1: 建立 PodcastProgress model**
```swift
// ios/BooksBrowser/Models/PodcastProgress.swift
import SwiftData

@Model
final class PodcastProgress {
    @Attribute(.unique) var episodeRemoteId: String = ""
    var lastPlayedTime: Double = 0
    var completed: Bool = false
    var updatedAt: Date = Date()

    init(episodeRemoteId: String, lastPlayedTime: Double = 0, completed: Bool = false) {
        self.episodeRemoteId = episodeRemoteId
        self.lastPlayedTime = lastPlayedTime
        self.updatedAt = Date()
    }
}
```

- [ ] **Step 2: 更新 BooksBrowserApp.swift schema**
逐一改動，注意 CloudStore vs LocalStore 區分：

| # | 位置 | 改動 |
|---|------|------|
| 1 | `cloudConfig` schema (L52-54) | 加 `PodcastProgress.self`（CloudKit 同步） |
| 2 | `allModels` 陣列 (L57) | 加 `PodcastProgress.self`（debug logging 用，需完整列表） |
| 3 | 主 `ModelContainer(for:)` (L60-61) | 加 `PodcastProgress.self` |
| 4 | `retryAfterStoreReset` 的 `localOnlyConfig` schema (L326-329) | 加 `PodcastProgress.self`（fallback 全 local 模式，所有 model 都需要） |
| 5 | `makeFallbackModelContainer` (L339-340) | 加 `PodcastProgress.self` |

**不改** `localConfig` schema (L47)：`PodcastProgress` 是 CloudStore model，不屬於 LocalStore。

- [ ] **Step 3: 移除 PodcastDebugSeed**
- 刪除 `PodcastDebugSeed.swift`
- 從 `BooksBrowserApp.swift` 移除 `PodcastDebugSeed.seedIfNeeded()` 呼叫
- 從 Xcode project 移除 `debug_podcast.mp3` 和 `debug_podcast.srt` 資源引用
- 刪除 `ios/BooksBrowser/Resources/debug_podcast.mp3` 和 `.srt`

- [ ] **Step 4: 更新 PodcastEpisode model**
確認 `audioURL` / `subtitleURL` 欄位語義改為後端 URL：
```swift
var audioURL: String?       // "https://wordnexus.lol/api/podcast-media/{series_id}/ep_{num}/audio.mp3"
var subtitleURL: String?    // "https://wordnexus.lol/api/podcasts/{series_id}/{ep_num}/subtitle"
```
保留 `localAudioPath` / `localSubtitlePath`（未來離線用，目前不使用）

- [ ] **Step 5: 寫 test**
```swift
// ios/BooksBrowserTests/PodcastProgressTests.swift
func test_podcast_progress_unique_episode_id() { ... }
func test_podcast_progress_update_time() { ... }
```

- [ ] **Step 6: Build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 7: Commit**
`ios: add PodcastProgress CloudKit model, remove debug seed + bundle assets`

---

## Task 4: iOS — PodcastSyncService

**Files:**
- Create: `ios/BooksBrowser/Services/PodcastSyncService.swift`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`
- Test: `ios/BooksBrowserTests/PodcastSyncTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
// ios/BooksBrowserTests/PodcastSyncTests.swift
func test_parse_series_list_response() {
    let json = """
    [{"id":"flow_950f1a7d","title":"Flow","episodeCount":8}]
    """.data(using: .utf8)!
    let series = try JSONDecoder().decode([PodcastSeriesSummary].self, from: json)
    XCTAssertEqual(series.count, 1)
    XCTAssertEqual(series[0].id, "flow_950f1a7d")
}

func test_parse_series_detail_response() {
    let json = """
    {"id":"flow_950f1a7d","title":"Flow","author":"Csikszentmihalyi",
     "hostNames":["Maya","Kai"],"color":"#5B8C5A","coverPattern":"waves",
     "totalDurationSec":11700,
     "episodes":[{"episodeNumber":1,"title":"The Happiness Trap","durationSec":1420,"audioAvailable":true,"subtitleAvailable":true}],
     "createdAt":"2026-04-12T20:00:00Z","updatedAt":"2026-04-12T21:30:00Z"}
    """.data(using: .utf8)!
    let detail = try JSONDecoder().decode(PodcastSeriesDetail.self, from: json)
    XCTAssertEqual(detail.episodes.count, 1)
    XCTAssertEqual(detail.hostNames, ["Maya", "Kai"])
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "PodcastSync"`
Expected: FAIL

- [ ] **Step 3: 寫 PodcastSyncService**
```swift
// ios/BooksBrowser/Services/PodcastSyncService.swift

// Response models (Codable)
struct PodcastSeriesSummary: Codable { ... }
struct PodcastSeriesDetail: Codable { ... }
struct PodcastEpisodeDetail: Codable { ... }

final class PodcastSyncService {
    private let baseURL: URL

    func fetchSeriesList() async throws -> [PodcastSeriesSummary]
    func fetchSeriesDetail(seriesId: String) async throws -> PodcastSeriesDetail

    /// 全量同步：拉 series list → 逐一拉 detail → 寫入 SwiftData
    func syncAll(context: ModelContext) async throws {
        let summaries = try await fetchSeriesList()
        for summary in summaries {
            let detail = try await fetchSeriesDetail(seriesId: summary.id)
            // upsert PodcastSeries + PodcastEpisode
            // remoteId 格式："{series_id}_ep_{zero_padded_num}"
            // audioURL / subtitleURL 拼接後端 URL
        }
    }
}
```

- [ ] **Step 4: 整合到 BookshelfView**
在 bookshelf `.task` 中呼叫 `PodcastSyncService.syncAll()`，app launch 時自動同步

- [ ] **Step 5: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "PodcastSync"`
Expected: PASS

- [ ] **Step 6: Commit**
`ios: add PodcastSyncService — backend metadata → SwiftData sync`

---

## Task 5: iOS — 渲染管線重構：SubtitleRenderState + ViewModel

**Files:**
- Create: `ios/BooksBrowser/Views/Podcast/SubtitleRenderState.swift`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastPlayerViewModel.swift`
- Modify: `ios/BooksBrowser/Services/PodcastSubtitleEngine.swift:49-51`
- Modify: `ios/BooksBrowser/Services/PodcastAudioEngine.swift:55-62`
- Test: `ios/BooksBrowserTests/SubtitleRenderStateTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
// ios/BooksBrowserTests/SubtitleRenderStateTests.swift
func test_word_render_items_normalized() {
    let sentence = PodcastSentence(id: 1, speaker: "Maya", text: "OK so here's the thing.", startTime: 0, endTime: 5, words: [])
    let hostNames = ["Maya", "Kai"]
    let state = SubtitleRenderState(from: sentence, hostNames: hostNames, palette: ...)
    XCTAssertEqual(state.words.count, 5)  // "OK", "so", "here's", "the", "thing."
    XCTAssertEqual(state.words[0].normalizedText, "ok")
    XCTAssertEqual(state.words[4].normalizedText, "thing")  // 標點 trimmed
}

func test_highlight_index_matches_normalized() {
    // highlightedWord "thing" should match word[4] whose normalizedText is "thing"
    let state = SubtitleRenderState(...)
    let index = state.highlightIndex(for: "thing")
    XCTAssertEqual(index, 4)
}

func test_subtitle_engine_sentence_binary_search() {
    let engine = PodcastSubtitleEngine()
    engine.parse(srtContent: testSRT)
    // 確認 currentSentence 用 binary search
    let sentence = engine.currentSentence(at: 5.0)
    XCTAssertNotNil(sentence)
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "SubtitleRenderState"`
Expected: FAIL

- [ ] **Step 3: 建立 SubtitleRenderState**
```swift
// ios/BooksBrowser/Views/Podcast/SubtitleRenderState.swift
struct WordRenderItem: Identifiable, Equatable {
    let id: Int
    let text: String
    let normalizedText: String
    let isHighlightTarget: Bool
}

struct SubtitleRenderState: Equatable {
    let sentenceId: Int
    let speaker: String
    let speakerColor: Color
    let words: [WordRenderItem]
    let sentenceText: String  // 完整 sentence，供翻譯 context

    init(from sentence: PodcastSentence, hostNames: [String], palette: VocabSkin.Palette) { ... }

    func highlightIndex(for normalizedWord: String) -> Int {
        words.firstIndex { $0.normalizedText == normalizedWord } ?? -1
    }
}
```

- [ ] **Step 4: 重構 PodcastPlayerViewModel**
核心變更：
- 新增 `renderState: SubtitleRenderState?`（低頻）
- 新增 `highlightedWordIndex: Int = -1`（高頻）
- 移除 `currentCue` 和 `currentSentence` 公開屬性（內部化）
- `handleTimeUpdate` 分離高/低頻路徑
- 新增 `rebuildRenderState(for:)` 私有方法

- [ ] **Step 5: 改 PodcastSubtitleEngine.currentSentence 為 binary search**
```swift
func currentSentence(at time: TimeInterval) -> PodcastSentence? {
    guard !sentences.isEmpty else { return nil }
    var lo = 0, hi = sentences.count - 1
    while lo <= hi {
        let mid = (lo + hi) / 2
        if sentences[mid].endTime < time { lo = mid + 1 }
        else if sentences[mid].startTime > time { hi = mid - 1 }
        else { return sentences[mid] }
    }
    // Fallback: last sentence whose startTime <= time
    return hi >= 0 ? sentences[hi] : nil
}
```

- [ ] **Step 6: Display link 降頻**
`PodcastAudioEngine.swift` 中把 display link 改為：
```swift
displayLink?.preferredFrameRateRange = CAFrameRateRange(minimum: 15, maximum: 30, preferred: 30)
```

- [ ] **Step 7: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "SubtitleRenderState"`
Expected: PASS

- [ ] **Step 8: Commit**
`ios: refactor subtitle render pipeline — SubtitleRenderState + binary search + 30fps`

---

## Task 6: iOS — WordLevelView + SentenceLevelView + FlowLayout 重構

**Files:**
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastWordLevelView.swift`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastSentenceLevelView.swift`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastSubtitleView.swift`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastControlsView.swift`（移除 displayMode，由 VM 管理）

- [ ] **Step 1: 重構 PodcastWordLevelView**
完全重寫，接收 `SubtitleRenderState` + `highlightedWordIndex`：
- 移除所有 `sentence.text.split()` 呼叫
- 移除 `isWordHighlighted()` 方法
- words 從 `renderState.words` 取得
- highlight 判斷 = `word.id == highlightedWordIndex`（O(1)）
- FlowLayout 改用 Layout protocol 的 `cache` 機制避免重複計算

- [ ] **Step 2: 重構 PodcastSentenceLevelView**
- 接收 `sentences: [PodcastSentence]`, `renderState`, `highlightedWordIndex`
- 視窗化：只渲染 `currentIndex ± 10`（用 computed property 算出 range）
- ScrollViewReader onChange 加 debounce：
  ```swift
  .onChange(of: renderState?.sentenceId) { _, newId in
      // 只在 sentence 切換時 scroll，不在 word highlight 變化時
      scrollDebounceTask?.cancel()
      scrollDebounceTask = Task {
          try? await Task.sleep(for: .milliseconds(100))
          withAnimation(AppMotion.standardSpring) {
              proxy.scrollTo(newId, anchor: .center)
          }
      }
  }
  ```

- [ ] **Step 3: 更新 PodcastSubtitleView**
改為傳遞 `renderState` + `highlightedWordIndex`，不再傳 `currentSentence` + `currentCue`

- [ ] **Step 4: Build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**
`ios: rewrite subtitle views — cached FlowLayout, windowed sentences, O(1) highlight`

---

## Task 7: iOS — PlayerView 接後端 + Translation Debounce + Progress 儲存

**Files:**
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastPlayerView.swift:102-138`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastTranslationHandler.swift:29-57`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastEpisodeListView.swift`

- [ ] **Step 1: 重寫 PodcastPlayerView.loadEpisode()**
移除所有 bundle fallback，改為：
```swift
func loadEpisode() async {
    // 1. 從 SwiftData 查詢 episode
    // 2. audioURL → URL(string:) → 下載到 tmp dir（URLSession.shared.download）
    // 3. subtitleURL → fetch SRT 文字（URLSession.shared.data）
    // 4. vm.loadEpisode(audioURL: localTmpURL, subtitleContent: srtString)
    // 5. 從 PodcastProgress (CloudStore) 載入上次播放位置
    //    若有 → vm.seek(to: lastPlayedTime)
}
```

注意：AVAudioEngine 不支援 HTTP streaming，需先下載到 tmp。
加 loading progress（下載 MB / 總 MB）。

- [ ] **Step 2: Translation debounce**
`PodcastTranslationHandler` 改為：
```swift
private var debounceTask: Task<Void, Never>?

func handleWordTap(word: String, context: String) {
    debounceTask?.cancel()
    debounceTask = Task {
        try? await Task.sleep(for: .milliseconds(300))
        guard !Task.isCancelled else { return }
        // 實際翻譯邏輯...
    }
}
```

- [ ] **Step 3: 播放進度自動儲存**
在 ViewModel 中加入 progress 儲存邏輯：
- 每 10 秒或 pause 時寫入 `PodcastProgress`
- 播完標記 `completed = true`
```swift
private var lastSavedTime: TimeInterval = 0
func handleTimeUpdate(_ time: TimeInterval) {
    // ... 既有邏輯
    if abs(time - lastSavedTime) > 10 {
        saveProgress(time: time)
        lastSavedTime = time
    }
}
```

- [ ] **Step 4: EpisodeListView 顯示進度**
從 CloudStore 查詢 `PodcastProgress`，episode row 顯示進度條

- [ ] **Step 5: Build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 6: Commit**
`ios: PlayerView backend loading + translation debounce + progress persistence`

---

## Task 8: 端對端驗證 — 上傳 Flow EP1 + iOS 播放

**Files:** 無新增

- [ ] **Step 1: 上傳 Flow EP1 到 server**
```bash
./ops/podcast_upload.sh lab/podcast/workspaces/flow_950f1a7d/
```
驗證 server 上 `/data/podcasts/flow_950f1a7d/ep_01/audio.mp3` 存在

- [ ] **Step 2: 驗證 API**
```bash
curl https://wordnexus.lol/api/podcasts | python -m json.tool
curl https://wordnexus.lol/api/podcasts/flow_950f1a7d | python -m json.tool
curl -I https://wordnexus.lol/api/podcast-media/flow_950f1a7d/ep_01/audio.mp3
# 確認 Accept-Ranges: bytes header
curl https://wordnexus.lol/api/podcasts/flow_950f1a7d/1/subtitle | head -20
```

- [ ] **Step 3: iOS 模擬器測試**
- 開 app → 書架出現 Flow podcast 卡片
- 點入 → episode list 顯示 EP1
- 點 EP1 → 下載 + 播放
- 字幕同步 word-level highlight
- 點詞翻譯觸發
- 切到 sentence mode 正常
- 暫停 → 重進 → 從上次位置繼續

- [ ] **Step 4: Deploy backend**
```bash
./ops/devops.sh deploy
```

- [ ] **Step 5: Commit（若有修正）**

---

## 執行順序與平行化

```
┌─────────────┐  ┌─────────────┐
│  Task 1     │  │  Task 2     │
│  Backend    │  │  Ops script  │
│  API        │  │  upload.sh   │
└──────┬──────┘  └──────┬──────┘
       │                │
       └────────┬───────┘
                │
       ┌────────▼────────┐
       │  Task 3         │
       │  iOS Models     │
       │  + CloudKit     │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Task 4         │
       │  SyncService    │
       └────────┬────────┘
                │
       ┌────────▼────────┐  ← 可平行
       │  Task 5         │
       │  RenderState    │
       │  + ViewModel    │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Task 6         │
       │  Views rewrite  │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Task 7         │
       │  PlayerView     │
       │  + backend load │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Task 8         │
       │  E2E validation │
       └─────────────────┘
```

**平行組**：Task 1 + Task 2 可完全平行。Task 5 的渲染重構不依賴 Task 4 的 SyncService，但建議在 Task 4 之後執行以確保 model 層穩定。
