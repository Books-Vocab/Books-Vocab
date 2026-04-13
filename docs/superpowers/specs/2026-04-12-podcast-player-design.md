# Podcast 播放器整合設計

## 動機

KG 的 `lab/podcast/` pipeline 已能將書籍轉換為雙人對談 podcast（EPUB → 多集腳本 → TTS 音訊 → word-level SRT 字幕）。目前只有 terminal preview（`ffplay`），需要在 iOS app 中提供完整的播放體驗，讓使用者在書架中點開 podcast series，瀏覽集數並播放。

## 設計決策摘要

| # | 項目 | 決策 |
|---|------|------|
| 1 | 資料模型 | 獨立 `PodcastSeries` + `PodcastEpisode` SwiftData model，與 `Notebook` 平行 |
| 2 | 書架整合 | 混排 grid，Podcast 卡片右上角 waveform badge 區分 |
| 3 | 字幕格式 | 現有 word-level SRT + `[Speaker]` prefix（pipeline 已改好） |
| 4 | 雙人字幕 UI | 單欄左對齊，左側色帶 + speaker chip 區分 |
| 5 | 音訊引擎 | AVAudioEngine + AVAudioUnitTimePitch（從 podcast-workspace 移植核心邏輯） |
| 6 | 變速 | 0.5x ~ 2.0x |
| 7 | 單字查詢 | 點擊字幕單字 → 復用 `Translating` 協定 + `TranslationPanel` |
| 8 | MVP 排除 | mini player、離線下載、進度持久化、背景播放、句子解釋面板 |

---

## 變更 1：資料模型

### SwiftData Models

```swift
@Model
final class PodcastSeries {
    var id: UUID
    var remoteId: String              // backend sync ID
    var title: String
    var color: String?                // hex，復用 NotebookPalette 12 色
    var coverPattern: String?         // dots|lines|grid|waves|circles|noise
    var coverImagePath: String?       // 自訂封面圖片本地路徑
    var hostNames: [String]           // e.g. ["Maya", "Kai"]
    var episodeCount: Int             // 快取，避免每次 count query
    var totalDurationSec: Double      // 快取，所有集數時長合計
    var sortOrder: Int = 0
    var createdAt: Date
    var updatedAt: Date
    var isDeleted: Bool = false

    @Relationship(deleteRule: .cascade)
    var episodes: [PodcastEpisode] = []
}

@Model
final class PodcastEpisode {
    var id: UUID
    var remoteId: String
    var series: PodcastSeries?        // inverse relationship
    var episodeNumber: Int
    var title: String
    var durationSec: Double
    var audioURL: String?             // backend URL（下載前）
    var localAudioPath: String?       // 下載後本地路徑
    var subtitleURL: String?          // backend URL
    var localSubtitlePath: String?    // 下載後本地路徑
    var audioAvailable: Bool = false
    var subtitleAvailable: Bool = false
    var createdAt: Date
    var updatedAt: Date
}
```

### Schema 註冊

在 `BooksBrowserApp` 的 `Schema` 陣列加入 `PodcastSeries.self` 和 `PodcastEpisode.self`。

### 與 Notebook 的關係

無直接關聯。透過書架 grid 的多型 item 混排，不共享任何 relationship。

---

## 變更 2：書架混排

### 現狀

`NotebookListView` 使用 `LazyVGrid` + `NavigationLink(value: notebook.remoteId)` 顯示 `NotebookCard`。

### 目標

grid 混排兩種 item，用 enum 統一：

```swift
enum BookshelfItem: Identifiable, Hashable {
    case notebook(Notebook)
    case podcastSeries(PodcastSeries)

    var id: String {
        switch self {
        case .notebook(let n): return "nb-\(n.remoteId)"
        case .podcastSeries(let p): return "ps-\(p.remoteId)"
        }
    }

    var sortDate: Date {
        switch self {
        case .notebook(let n): return n.updatedAt
        case .podcastSeries(let p): return p.updatedAt
        }
    }
}
```

### NotebookListView 修改

```swift
// 現有 @Query
@Query(...) private var notebooks: [Notebook]
// 新增
@Query(filter: #Predicate<PodcastSeries> { !$0.isDeleted },
       sort: \.sortOrder) private var podcastSeries: [PodcastSeries]

// 合併為 bookshelfItems，按 sortOrder 排列
var bookshelfItems: [BookshelfItem] {
    let nb = notebooks.map { BookshelfItem.notebook($0) }
    let ps = podcastSeries.map { BookshelfItem.podcastSeries($0) }
    return (nb + ps).sorted { $0.sortDate > $1.sortDate }
}
```

### Grid 渲染

```swift
LazyVGrid(columns: [...]) {
    ForEach(bookshelfItems) { item in
        switch item {
        case .notebook(let notebook):
            NavigationLink(value: BookshelfDestination.notebook(notebook.remoteId)) {
                NotebookCard(data: cardData(for: notebook))
            }
        case .podcastSeries(let series):
            NavigationLink(value: BookshelfDestination.podcast(series.remoteId)) {
                NotebookCard(data: cardData(for: series))
                    .overlay(alignment: .topTrailing) {
                        PodcastBadge()
                    }
            }
        }
    }
}
```

### Navigation destination

```swift
enum BookshelfDestination: Hashable {
    case notebook(String)    // remoteId
    case podcast(String)     // remoteId
}

.navigationDestination(for: BookshelfDestination.self) { dest in
    switch dest {
    case .notebook(let id):
        VocabularyListView(notebookId: id)
    case .podcast(let id):
        PodcastEpisodeListView(seriesId: id)
    }
}
```

### PodcastBadge

```swift
/// 右上角 waveform icon，標記此卡片是 podcast
struct PodcastBadge: View {
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        Image(systemName: "waveform")
            .font(.caption2.weight(.bold))
            .foregroundStyle(skin.palette.onSurfaceMuted)
            .padding(skin.spacing.chipPaddingH)
            .background(
                Capsule()
                    .fill(skin.palette.surfaceElevated.opacity(0.85))
            )
            .padding(skin.spacing.cardPadding / 2)
    }
}
```

### Podcast 卡片資料映射

Podcast 復用 `NotebookCardData`，映射：

| NotebookCardData 欄位 | Podcast 對應 |
|---|---|
| `name` | series.title |
| `color` | series.color |
| `coverPattern` | series.coverPattern |
| `coverImagePath` | series.coverImagePath |
| `cardCount` | series.episodeCount |
| `cardCountLabel` | `"集"` (取代 `"個單字"`) |
| `dueCount` | 0（podcast 無複習概念） |
| `unlearnedCount` | 0 |
| `reviewedCount` | 0 |
| `pendingCount` | 0 |
| `isActive` | false |
| `lastActivity` | series.updatedAt |

需在 `NotebookCardData` 新增 `cardCountLabel: String` 欄位（預設 `"個單字"`），讓 podcast 可傳入 `"集"`。review 相關欄位全部傳 0，卡片的 `ProgressCapsule` 和 due/unlearned chip 自然不顯示。

---

## 變更 3：集數列表

### PodcastEpisodeListView

點擊 podcast 卡片後進入。類似 `ChapterListView` 但遵守 KG design system。

```
┌──────────────────────────────────┐
│  ← 心流：最優體驗心理學            │  ← navigation title
│                                  │
│  ┌────────────────────────────┐  │
│  │ ▊ Ep 1 · The Happiness Trap│  │
│  │   23:40 · 🎙️ 🔤           │  │  ← 時長 + 音訊/字幕 availability
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │ ▊ Ep 2 · The Anatomy of...│  │
│  │   28:15 · 🎙️ 🔤           │  │
│  └────────────────────────────┘  │
│  ...                             │
└──────────────────────────────────┘
```

### 元件結構

```swift
/// 避免與其他 String-based navigationDestination 衝突
struct PodcastEpisodeDestination: Hashable {
    let episodeId: String
}

struct PodcastEpisodeListView: View {
    let seriesId: String
    @Query private var episodes: [PodcastEpisode]  // filtered by series
    @Environment(\.vocabSkin) private var skin
    @Environment(\.appTheme) private var theme

    var body: some View {
        List {
            ForEach(sortedEpisodes) { episode in
                NavigationLink(value: PodcastEpisodeDestination(episodeId: episode.remoteId)) {
                    PodcastEpisodeRow(episode: episode)
                }
                .disabled(!episode.audioAvailable)
            }
        }
        .navigationTitle(seriesTitle)
        .navigationDestination(for: PodcastEpisodeDestination.self) { dest in
            PodcastPlayerView(episodeId: dest.episodeId)
        }
    }
}
```

### PodcastEpisodeRow

```swift
struct PodcastEpisodeRow: View {
    let episode: PodcastEpisode
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        VStack(alignment: .leading, spacing: skin.spacing.rowInternalGap) {
            // 標題
            Text(episode.displayTitle)
                .font(skin.typography.cardTitle)
                .foregroundStyle(skin.palette.onSurface)

            // metadata 行
            HStack(spacing: skin.spacing.chipGap) {
                // 時長
                Text(formatDuration(episode.durationSec))
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.onSurfaceMuted)

                // 音訊可用
                if episode.audioAvailable {
                    Image(systemName: "waveform.circle.fill")
                        .font(.caption)
                        .foregroundStyle(skin.palette.accent)
                }

                // 字幕可用
                if episode.subtitleAvailable {
                    Image(systemName: "captions.bubble.fill")
                        .font(.caption)
                        .foregroundStyle(skin.palette.success)
                }
            }
        }
        .padding(.vertical, skin.spacing.rowVerticalPadding)
    }
}
```

---

## 變更 4：播放器

### 架構概覽

```
PodcastPlayerView
├── PodcastPlayerViewModel (@Observable, @MainActor)
│   ├── PodcastAudioEngine (AVAudioEngine + TimePitch)
│   ├── PodcastSubtitleEngine (SRT parse + sync)
│   └── TranslationService (復用 Translating 協定)
├── PodcastSubtitleView (雙人字幕顯示)
├── PodcastControlsView (播放/暫停/skip/seek/變速)
└── TranslationPanel (復用 Reader 現有元件)
```

### PodcastAudioEngine

從 podcast-workspace 的 `AudioEngineManager` 移植核心邏輯，適配 KG：

```swift
/// 純音訊引擎，不含 UI 邏輯
final class PodcastAudioEngine {
    private var audioEngine: AVAudioEngine
    private var playerNode: AVAudioPlayerNode
    private var timePitchNode: AVAudioUnitTimePitch

    func loadAudio(url: URL) throws
    func play()
    func pause()
    func seek(to time: TimeInterval, autoResume: Bool)
    func setRate(_ rate: Float)   // 0.5 ~ 2.0
    var currentTime: TimeInterval  // CADisplayLink 驅動，每幀更新（~60Hz）
    var duration: TimeInterval
    var isPlaying: Bool

    /// 時間更新回調，由 CADisplayLink 驅動以確保字幕逐詞同步精度
    var onTimeUpdate: ((TimeInterval) -> Void)?
}
```

### PodcastSubtitleEngine

解析 SRT，管理時間同步與 speaker 識別：

```swift
/// 解析後的字幕 cue
struct PodcastSubtitleCue: Identifiable {
    let id: Int
    let startTime: TimeInterval
    let endTime: TimeInterval
    let speaker: String           // "Maya" / "Kai"
    let fullText: String          // 完整句子（不含 speaker tag）
    let highlightedWord: String?  // 當前高亮的詞（from <font> tag）
    let highlightRange: Range<String.Index>?
}

/// sentence-level 聚合
struct PodcastSentence: Identifiable {
    let id: Int
    let speaker: String
    let text: String              // 完整句子
    let startTime: TimeInterval
    let endTime: TimeInterval
    let words: [PodcastSubtitleCue]  // 此句的所有 word-level cues
}

final class PodcastSubtitleEngine {
    private(set) var sentences: [PodcastSentence] = []
    private(set) var cues: [PodcastSubtitleCue] = []

    func load(srtContent: String)
    func currentSentence(at time: TimeInterval) -> PodcastSentence?
    func currentCue(at time: TimeInterval) -> PodcastSubtitleCue?
}
```

### SRT 解析邏輯

```
輸入：
1
00:00:00,260 --> 00:00:00,440
[Maya] <font color="#00ff00">OK so</font> here's a question that's been bugging me.

解析步驟：
1. 提取 [Speaker] → "Maya"
2. 剝離 <font> tag → highlightedWord = "OK so"
3. 剝離所有 HTML → fullText = "OK so here's a question that's been bugging me."
4. 聚合相同 fullText 的連續 cues → 一個 PodcastSentence
```

### PodcastPlayerViewModel

```swift
@MainActor @Observable
final class PodcastPlayerViewModel {
    // 狀態
    enum PlayerState { case idle, loading, ready, playing, paused, error(String) }

    private(set) var state: PlayerState = .idle
    private(set) var currentTime: TimeInterval = 0
    private(set) var duration: TimeInterval = 0
    private(set) var currentSentence: PodcastSentence?
    private(set) var currentCue: PodcastSubtitleCue?
    private(set) var playbackRate: Float = 1.0
    private(set) var displayMode: SubtitleDisplayMode = .wordLevel

    // 翻譯
    var translationHandler: PodcastTranslationHandler?

    // 引擎
    private let audioEngine = PodcastAudioEngine()
    private let subtitleEngine = PodcastSubtitleEngine()

    // 操作
    func loadEpisode(_ episode: PodcastEpisode) async
    func play()
    func pause()
    func togglePlayPause()
    func seek(to time: TimeInterval)
    func skip(seconds: Double)      // ±15
    func setRate(_ rate: Float)
    func setDisplayMode(_ mode: SubtitleDisplayMode)
    func handleWordTap(word: String, context: String)
}
```

### 顯示模式

```swift
enum SubtitleDisplayMode {
    case wordLevel     // 逐詞高亮，一次顯示一句
    case sentenceLevel // 顯示多句滾動列表，當前句高亮
}
```

---

## 變更 5：雙人字幕 UI

### Word-Level 模式

一次顯示一句，逐詞高亮：

```
┌──────────────────────────────────┐
│                                  │
│  ┌─ Maya ─────────────────────┐  │
│  │█                           │  │  ← 左側色帶（speaker 顏色）
│  │█ OK so here's a question   │  │
│  │█ that's been bugging me.   │  │  ← "bugging" 高亮
│  │█                           │  │
│  └────────────────────────────┘  │
│                                  │
└──────────────────────────────────┘
```

- 左側 3pt 圓角色帶，speaker A 用 `skin.palette.accent`，speaker B 用 `skin.palette.success`
- Speaker chip：小膠囊，speaker 名字，位於色帶上方
- 高亮詞：`skin.palette.accent` 背景 + `skin.palette.onAccent` 文字
- 非高亮詞：`skin.palette.onSurface` 文字
- 點擊任意詞 → 觸發翻譯流程

### Sentence-Level 模式

多句滾動列表，當前句高亮：

```
┌──────────────────────────────────┐
│  ┌─ Maya ─────────────────────┐  │
│  │█ OK so here's a question   │  │  ← 淡化
│  │█ that's been bugging me... │  │
│  └────────────────────────────┘  │
│  ┌─ Kai ──────────────────────┐  │
│  │█ And that's exactly where  │  │  ← 當前：不透明度 100%
│  │█ this book starts...       │  │
│  └────────────────────────────┘  │
│  ┌─ Maya ─────────────────────┐  │
│  │█ [laughing] I'm keeping    │  │  ← 淡化
│  │█ a tally.                  │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘
```

- 當前句：opacity 1.0，其他：opacity 0.4
- 自動滾動到當前句（`ScrollViewReader` + `scrollTo`）
- 點擊非當前句 → seek 到該句起始時間

### PodcastSubtitleView

```swift
struct PodcastSubtitleView: View {
    let viewModel: PodcastPlayerViewModel
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        switch viewModel.displayMode {
        case .wordLevel:
            PodcastWordLevelView(
                sentence: viewModel.currentSentence,
                currentCue: viewModel.currentCue,
                onWordTap: viewModel.handleWordTap
            )
        case .sentenceLevel:
            PodcastSentenceLevelView(
                sentences: viewModel.visibleSentences,
                currentSentenceId: viewModel.currentSentence?.id,
                onSentenceTap: { viewModel.seek(to: $0.startTime) },
                onWordTap: viewModel.handleWordTap
            )
        }
    }
}
```

### Speaker 色帶元件

```swift
struct SpeakerAccentBar: View {
    let speaker: String
    let hostNames: [String]
    @Environment(\.vocabSkin) private var skin

    private var barColor: Color {
        guard let index = hostNames.firstIndex(of: speaker) else {
            return skin.palette.onSurfaceMuted
        }
        return index == 0 ? skin.palette.accent : skin.palette.success
    }

    var body: some View {
        RoundedRectangle(cornerRadius: skin.radii.tiny)
            .fill(barColor)
            .frame(width: 3)
    }
}
```

---

## 變更 6：播放控制 UI

### PodcastControlsView

```
┌──────────────────────────────────┐
│  ▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔  │  ← seek bar（Capsule track）
│  02:34              23:40        │  ← 時間標籤
│                                  │
│    ⏪15    ▶️/⏸    ⏩15           │  ← 控制按鈕
│                                  │
│  [W] word · [S] sentence  ×1.0  │  ← 模式切換 + 變速
└──────────────────────────────────┘
```

- Seek bar：復用 Capsule track 風格（AppMetrics cornerRadius），不搬 podcast-workspace 的 `ProgressSlider`
- 控制按鈕：SF Symbols，`skin.palette.accent` 色
- 模式切換：segmented-style chip（word / sentence）
- 變速：tap 循環 0.5 → 0.75 → 1.0 → 1.25 → 1.5 → 2.0 → 0.5（回到起點），顯示 `×1.0` chip

### 動畫

- 播放/暫停切換：`AppMotion.standardSpring`
- 字幕句切換：`AppMotion.contentReveal` transition
- 高亮詞跳動：`AppMotion.feedbackPulse`
- seek bar 拖曳：`AppMotion.swipeTrackingSpring`

---

## 變更 7：單字查詢整合

### 流程

1. 使用者點擊字幕中的一個詞
2. `PodcastPlayerViewModel.handleWordTap(word:context:)` 被呼叫
3. context = 當前 sentence 的 fullText
4. 建立 `PodcastTranslationHandler`（包裝 `Translating` 協定）
5. 呼叫 `translationService.translateQuick(word:context:)`
6. 顯示 `TranslationPanel`（復用 Reader 的 panel 元件）
7. 翻譯完成 → 自動存入詞彙本（activeNotebookId）

### PodcastTranslationHandler

```swift
@Observable @MainActor
final class PodcastTranslationHandler {
    private let translationService: Translating
    private let vocabularyContext: ReaderVocabularyContext

    var wordSelection: WordSelection?
    var translationResult: TranslationResult?
    var isTranslating: Bool = false
    var isSaved: Bool = false

    func handleWordTap(word: String, context: String)
    func dismiss()
}
```

邏輯與 `ReaderTranslationHandler.handleWordSelected` 相同：
1. normalize word
2. 檢查是否已存在於詞彙本
3. 呼叫 `translateQuick`
4. auto-save 到 active notebook

### UI 呈現

播放器底部 overlay `TranslationPanel`，與 Reader 共用同一元件：

```swift
.overlay(alignment: .bottom) {
    if translationHandler.wordSelection != nil {
        TranslationPanel(handler: translationHandler)
            .transition(.readerPanelReveal)
    }
}
```

---

## 檔案結構

```
ios/BooksBrowser/
├── Models/
│   ├── PodcastSeries.swift          // SwiftData model
│   └── PodcastEpisode.swift         // SwiftData model
├── Views/Podcast/
│   ├── PodcastEpisodeListView.swift // 集數列表
│   ├── PodcastEpisodeRow.swift      // 集數列表行
│   ├── PodcastPlayerView.swift      // 播放器主畫面
│   ├── PodcastControlsView.swift    // 播放控制
│   ├── PodcastSubtitleView.swift    // 字幕容器（雙模式）
│   ├── PodcastWordLevelView.swift   // word-level 字幕
│   ├── PodcastSentenceLevelView.swift // sentence-level 字幕
│   ├── SpeakerAccentBar.swift       // speaker 色帶元件
│   ├── PodcastBadge.swift           // 書架 waveform badge
│   └── PodcastTranslationHandler.swift // 單字查詢橋接
├── Services/
│   ├── PodcastAudioEngine.swift     // AVAudioEngine 封裝
│   └── PodcastSubtitleEngine.swift  // SRT 解析 + 時間同步
└── Views/Vocabulary/Scenes/
    └── NotebookListView.swift       // 修改：混排 BookshelfItem
```

---

## 測試資料策略

MVP 不接後端 API。測試資料來源：

1. **Bundle test assets** — 從 `lab/podcast/workspaces/flow_950f1a7d/scripts/` 取一集的 MP3 + SRT，加入 Xcode 的 Copy Bundle Resources
2. **Preview seed** — `#Preview` 中用 `PodcastSeries` / `PodcastEpisode` 的 in-memory 實例
3. **Debug seed** — `#if DEBUG` 區塊在首次啟動時，若 SwiftData 中無 PodcastSeries，自動建立一筆 seed data 指向 bundle 中的測試音訊

這樣無需後端即可完整測試播放器全流程。

---

## 不做（MVP 排除）

| 功能 | 理由 |
|------|------|
| Mini player | 需要 app 層級狀態管理，複雜度高 |
| 離線下載 | 需要 download manager + cache policy |
| 進度持久化 | 需要 SwiftData 欄位 + 書架進度條 |
| 背景播放 / NowPlaying | 需要 MPNowPlayingInfoCenter + audio session 管理 |
| 句子解釋面板 | Reader 的 explain flow 較重，先不搬 |
| 後端 API | 先用本地測試資料，API 另案設計 |

## 狀態覆蓋

| 畫面 | loading | empty | error | success |
|------|---------|-------|-------|---------|
| 集數列表 | Skeleton list | 「尚無集數」+ waveform icon | 「載入失敗」+ retry | 集數列表 |
| 播放器 | ProgressView + 「載入音訊…」 | N/A | 「音訊載入失敗」+ retry | 播放介面 |
| 字幕 | — | 「無字幕」placeholder | — | 字幕顯示 |
| 翻譯 panel | spinner | — | 錯誤訊息 | 翻譯結果 |
