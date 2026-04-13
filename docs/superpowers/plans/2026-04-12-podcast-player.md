# Podcast 播放器整合 Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 在 KG iOS 書架中整合 Podcast 播放功能 — 書架混排、集數列表、雙人字幕播放器、單字查詢。
**Architecture:** 新增獨立 SwiftData model（PodcastSeries / PodcastEpisode），書架 grid 多型混排，AVAudioEngine 播放引擎，復用 Translating 協定做單字查詢。
**Tech Stack:** SwiftUI + SwiftData + AVAudioEngine + AVAudioUnitTimePitch

---

### Task 1: SwiftData Models — PodcastSeries + PodcastEpisode

**Files:**
- Create: `ios/BooksBrowser/Models/PodcastSeries.swift`
- Create: `ios/BooksBrowser/Models/PodcastEpisode.swift`
- Modify: `ios/BooksBrowser/BooksBrowserApp.swift:45-63` (Schema registration)
- Test: `ios/BooksBrowserTests/PodcastModelTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
import Testing
import SwiftData
@testable import BooksBrowser

struct PodcastModelTests {
    @Test func podcastSeriesCreation() throws {
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self,
            configurations: config
        )
        let context = ModelContext(container)

        let series = PodcastSeries(
            remoteId: "test-series",
            title: "Flow: The Psychology of Optimal Experience",
            hostNames: ["Maya", "Kai"]
        )
        context.insert(series)

        let episode = PodcastEpisode(
            remoteId: "ep-1",
            episodeNumber: 1,
            title: "The Happiness Trap",
            durationSec: 1420
        )
        episode.series = series
        context.insert(episode)
        try context.save()

        let fetched = try context.fetch(FetchDescriptor<PodcastSeries>())
        #expect(fetched.count == 1)
        #expect(fetched[0].episodes.count == 1)
        #expect(fetched[0].hostNames == ["Maya", "Kai"])
    }

    @Test func podcastEpisodeSorting() throws {
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self,
            configurations: config
        )
        let context = ModelContext(container)

        let series = PodcastSeries(remoteId: "s1", title: "Test", hostNames: [])
        context.insert(series)

        for i in [3, 1, 2] {
            let ep = PodcastEpisode(
                remoteId: "ep-\(i)",
                episodeNumber: i,
                title: "Episode \(i)",
                durationSec: 600
            )
            ep.series = series
            context.insert(ep)
        }
        try context.save()

        var descriptor = FetchDescriptor<PodcastEpisode>(
            sortBy: [SortDescriptor(\.episodeNumber)]
        )
        let episodes = try context.fetch(descriptor)
        #expect(episodes.map(\.episodeNumber) == [1, 2, 3])
    }

    @Test func cascadeDelete() throws {
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self,
            configurations: config
        )
        let context = ModelContext(container)

        let series = PodcastSeries(remoteId: "s1", title: "Test", hostNames: [])
        context.insert(series)
        let ep = PodcastEpisode(remoteId: "ep-1", episodeNumber: 1, title: "Ep 1", durationSec: 300)
        ep.series = series
        context.insert(ep)
        try context.save()

        context.delete(series)
        try context.save()

        let remaining = try context.fetch(FetchDescriptor<PodcastEpisode>())
        #expect(remaining.isEmpty)
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "PodcastModel"`
Expected: FAIL (PodcastSeries / PodcastEpisode 不存在)

- [ ] **Step 3: 實作 PodcastSeries.swift**
```swift
import Foundation
import SwiftData

@Model
final class PodcastSeries {
    var id: UUID = UUID()
    var remoteId: String
    var title: String
    var color: String?
    var coverPattern: String?
    var coverImagePath: String?
    var hostNames: [String]
    var episodeCount: Int = 0
    var totalDurationSec: Double = 0
    var sortOrder: Int = 0
    var createdAt: Date = Date()
    var updatedAt: Date = Date()
    var isDeleted: Bool = false

    @Relationship(deleteRule: .cascade, inverse: \PodcastEpisode.series)
    var episodes: [PodcastEpisode] = []

    init(remoteId: String, title: String, hostNames: [String]) {
        self.remoteId = remoteId
        self.title = title
        self.hostNames = hostNames
    }
}
```

- [ ] **Step 4: 實作 PodcastEpisode.swift**
```swift
import Foundation
import SwiftData

@Model
final class PodcastEpisode {
    var id: UUID = UUID()
    var remoteId: String
    var series: PodcastSeries?
    var episodeNumber: Int
    var title: String
    var durationSec: Double
    var audioURL: String?
    var localAudioPath: String?
    var subtitleURL: String?
    var localSubtitlePath: String?
    var audioAvailable: Bool = false
    var subtitleAvailable: Bool = false
    var createdAt: Date = Date()
    var updatedAt: Date = Date()

    init(remoteId: String, episodeNumber: Int, title: String, durationSec: Double) {
        self.remoteId = remoteId
        self.episodeNumber = episodeNumber
        self.title = title
        self.durationSec = durationSec
    }

    var displayTitle: String {
        "Ep \(episodeNumber) · \(title)"
    }
}
```

- [ ] **Step 5: 註冊到 Schema**
`BooksBrowserApp.swift` 修改：
- `localConfig` Schema 加入 `PodcastSeries.self, PodcastEpisode.self`
- `ModelContainer(for:)` 加入兩個型別
- `allModels` 陣列加入

- [ ] **Step 6: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "PodcastModel"`

- [ ] **Step 7: Commit**
`ios: add PodcastSeries + PodcastEpisode SwiftData models`

---

### Task 2: 書架混排 — BookshelfItem + BookshelfDestination + NotebookCard 擴充

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/BookshelfItem.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookCard.swift:3-15,70,122`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:12-15,78-132,160-162`
- Create: `ios/BooksBrowser/Views/Podcast/PodcastBadge.swift`
- Test: `ios/BooksBrowserTests/BookshelfItemTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
import Testing
@testable import BooksBrowser

struct BookshelfItemTests {
    @Test func notebookCardDataWithCustomLabel() {
        let data = NotebookCardData(
            name: "Flow Podcast",
            color: "#4A90D9",
            coverPattern: "waves",
            coverImagePath: nil,
            cardCount: 8,
            cardCountLabel: "集",
            dueCount: 0,
            unlearnedCount: 0,
            reviewedCount: 0,
            pendingCount: 0,
            lastActivity: Date(),
            isActive: false
        )
        #expect(data.cardCountLabel == "集")
    }

    @Test func notebookCardDataDefaultLabel() {
        let data = NotebookCardData(
            name: "My Vocab",
            color: nil,
            coverPattern: nil,
            coverImagePath: nil,
            cardCount: 42,
            dueCount: 5,
            unlearnedCount: 3,
            reviewedCount: 34,
            pendingCount: 0,
            lastActivity: nil,
            isActive: true
        )
        #expect(data.cardCountLabel == "個單字")
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "BookshelfItem"`
Expected: FAIL (cardCountLabel 欄位不存在)

- [ ] **Step 3: NotebookCardData 加 cardCountLabel**
`NotebookCard.swift` ��改 `NotebookCardData`：
```swift
struct NotebookCardData {
    let name: String
    let color: String?
    let coverPattern: String?
    let coverImagePath: String?
    let cardCount: Int
    var cardCountLabel: String = "個單字"  // podcast 傳 "集"
    let dueCount: Int
    let unlearnedCount: Int
    let reviewedCount: Int
    let pendingCount: Int
    let lastActivity: Date?
    let isActive: Bool
}
```

修改 label 顯示（line 70）：
```swift
// 改 "\(data.cardCount) 個單字" 為：
Label("\(data.cardCount) \(data.cardCountLabel)", systemImage: "character.book.closed")
```

修改 accessibility（line 122）：
```swift
// 改 "\(data.cardCount) 個單字" 為：
var parts = [data.name, "\(data.cardCount) \(data.cardCountLabel)"]
```

- [ ] **Step 4: 建立 BookshelfItem.swift**
```swift
import Foundation

enum BookshelfDestination: Hashable {
    case notebook(String)
    case podcast(String)
}

// SwiftData @Model classes conform to Hashable via PersistentIdentifier.
// Wrapping in enum is safe because @Model synthesizes Hashable.
enum BookshelfItem: Identifiable, Hashable {
    case notebook(Notebook)
    case podcastSeries(PodcastSeries)

    var id: String {
        switch self {
        case .notebook(let n): "nb-\(n.remoteId)"
        case .podcastSeries(let p): "ps-\(p.remoteId)"
        }
    }

    var sortDate: Date {
        switch self {
        case .notebook(let n): n.updatedAt
        case .podcastSeries(let p): p.updatedAt
        }
    }
}
```

- [ ] **Step 5: 建立 PodcastBadge.swift**
```swift
import SwiftUI

struct PodcastBadge: View {
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        Image(systemName: "waveform")
            .font(.caption2.weight(.bold))
            .foregroundStyle(skin.palette.primaryTextMuted)
            .padding(.horizontal, skin.spacing.chipHorizontalPadding)
            .padding(.vertical, skin.spacing.chipVerticalPadding)
            .background(
                Capsule()
                    .fill(skin.palette.mutedFill.opacity(0.85))
            )
            .padding(skin.spacing.cardPadding / 2)
    }
}
```

- [ ] **Step 6: NotebookListView 改 BookshelfDestination routing**
修改 `NotebookListView.swift`：

1. 加 `@Query` for PodcastSeries：
```swift
@Query(filter: #Predicate<PodcastSeries> { !$0.isDeleted }, sort: \.sortOrder)
private var podcastSeries: [PodcastSeries]
```

2. 合併 bookshelfItems computed property：
```swift
private var bookshelfItems: [BookshelfItem] {
    let nb = notebooks.map { BookshelfItem.notebook($0) }
    let ps = podcastSeries.map { BookshelfItem.podcastSeries($0) }
    return (nb + ps).sorted { $0.sortDate > $1.sortDate }
}
```

3. grid ForEach 改用 bookshelfItems + switch：
```swift
ForEach(bookshelfItems) { item in
    switch item {
    case .notebook(let notebook):
        let s = stats[notebook.remoteId] ?? NotebookStats()
        NavigationLink(value: BookshelfDestination.notebook(notebook.remoteId)) {
            NotebookCard(data: NotebookCardData(
                name: notebook.name,
                color: notebook.color,
                coverPattern: notebook.coverPattern,
                coverImagePath: notebook.coverImagePath,
                cardCount: s.cardCount,
                dueCount: s.dueCount,
                unlearnedCount: s.unlearnedCount,
                reviewedCount: s.reviewedCount,
                pendingCount: s.pendingCount,
                lastActivity: s.lastActivity,
                isActive: notebook.remoteId == activeNotebookId
            ))
        }
        .buttonStyle(.plain)
        .contextMenu { /* existing notebook context menu */ }

    case .podcastSeries(let series):
        NavigationLink(value: BookshelfDestination.podcast(series.remoteId)) {
            NotebookCard(data: NotebookCardData(
                name: series.title,
                color: series.color,
                coverPattern: series.coverPattern,
                coverImagePath: series.coverImagePath,
                cardCount: series.episodeCount,
                cardCountLabel: "集",
                dueCount: 0,
                unlearnedCount: 0,
                reviewedCount: 0,
                pendingCount: 0,
                lastActivity: series.updatedAt,
                isActive: false
            ))
            .overlay(alignment: .topTrailing) {
                PodcastBadge()
            }
        }
        .buttonStyle(.plain)
    }
}
```

4. navigationDestination 改為 BookshelfDestination：
```swift
.navigationDestination(for: BookshelfDestination.self) { dest in
    switch dest {
    case .notebook(let id):
        VocabularyListView(notebookId: id)
    case .podcast(let id):
        PodcastEpisodeListView(seriesId: id)
    }
}
```

- [ ] **Step 7: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "BookshelfItem"`

- [ ] **Step 8: Commit**
`ios: bookshelf — polymorphic grid with notebook + podcast mixed layout`

---

### Task 3: PodcastAudioEngine — AVAudioEngine 播放引擎

**Files:**
- Create: `ios/BooksBrowser/Services/PodcastAudioEngine.swift`
- Test: `ios/BooksBrowserTests/PodcastAudioEngineTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
import Testing
import AVFoundation
@testable import BooksBrowser

struct PodcastAudioEngineTests {
    @Test func loadAudioSetsCorrectDuration() throws {
        let engine = PodcastAudioEngine()
        let url = Bundle(for: BundleToken.self).url(forResource: "test_podcast_clip", withExtension: "mp3")!
        try engine.loadAudio(url: url)
        #expect(engine.duration > 0)
        #expect(!engine.isPlaying)
    }

    @Test func setRateClampsToValidRange() {
        let engine = PodcastAudioEngine()
        engine.setRate(0.1)
        #expect(engine.playbackRate == 0.5)
        engine.setRate(3.0)
        #expect(engine.playbackRate == 2.0)
        engine.setRate(1.25)
        #expect(engine.playbackRate == 1.25)
    }

    @Test func rateSteps() {
        let steps = PodcastAudioEngine.rateSteps
        #expect(steps == [0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
    }

    @Test func nextRateCycles() {
        #expect(PodcastAudioEngine.nextRate(after: 1.0) == 1.25)
        #expect(PodcastAudioEngine.nextRate(after: 2.0) == 0.5)
        #expect(PodcastAudioEngine.nextRate(after: 0.5) == 0.75)
    }
}

private class BundleToken {}
```

需要一個短 MP3 測試檔。從 `lab/podcast/workspaces/flow_950f1a7d/scripts/` 截取前 5 秒：
```bash
ffmpeg -i lab/podcast/workspaces/flow_950f1a7d/scripts/ep_1_pro.mp3 -t 5 -c copy ios/BooksBrowserTests/Resources/test_podcast_clip.mp3
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "PodcastAudioEngine"`

- [ ] **Step 3: 實作 PodcastAudioEngine**
```swift
import Foundation
import AVFoundation

final class PodcastAudioEngine: NSObject {
    private var audioEngine = AVAudioEngine()
    private var playerNode = AVAudioPlayerNode()
    private var timePitchNode = AVAudioUnitTimePitch()
    private var audioFile: AVAudioFile?
    private var segmentStartTime: TimeInterval = 0
    private var ignoreNextCompletion = false
    private var displayLink: CADisplayLink?

    private(set) var playbackRate: Float = 1.0
    var onTimeUpdate: ((TimeInterval) -> Void)?
    var onPlaybackFinished: (() -> Void)?

    static let rateSteps: [Float] = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    static func nextRate(after current: Float) -> Float {
        guard let idx = rateSteps.firstIndex(where: { abs($0 - current) < 0.01 }) else {
            return 1.0
        }
        return rateSteps[(idx + 1) % rateSteps.count]
    }

    override init() {
        super.init()
        audioEngine.attach(playerNode)
        audioEngine.attach(timePitchNode)
    }

    deinit {
        displayLink?.invalidate()
        audioEngine.stop()
    }

    func loadAudio(url: URL) throws {
        if audioEngine.isRunning { audioEngine.stop() }
        ignoreNextCompletion = true
        playerNode.stop()

        audioFile = try AVAudioFile(forReading: url)
        guard let audioFile else { throw PodcastAudioEngineError.invalidFile }

        let format = audioFile.processingFormat
        audioEngine.disconnectNodeOutput(playerNode)
        audioEngine.disconnectNodeOutput(timePitchNode)
        audioEngine.connect(playerNode, to: timePitchNode, format: format)
        audioEngine.connect(timePitchNode, to: audioEngine.mainMixerNode, format: format)
        timePitchNode.rate = playbackRate

        try audioEngine.start()
        segmentStartTime = 0
        scheduleFile()
        ignoreNextCompletion = false
    }

    func play() {
        if !audioEngine.isRunning { try? audioEngine.start() }
        playerNode.play()
        startDisplayLink()
    }

    func pause() {
        playerNode.pause()
        stopDisplayLink()
    }

    func seek(to time: TimeInterval, autoResume: Bool) {
        guard let audioFile else { return }
        let sampleRate = audioFile.processingFormat.sampleRate
        let startFrame = AVAudioFramePosition(time * sampleRate)
        let frameCount = audioFile.length - startFrame
        guard startFrame >= 0, frameCount > 0 else { return }

        ignoreNextCompletion = true
        playerNode.stop()
        playerNode.scheduleSegment(
            audioFile,
            startingFrame: startFrame,
            frameCount: AVAudioFrameCount(frameCount),
            at: nil
        ) { [weak self] in self?.handleCompletion() }
        segmentStartTime = time
        if autoResume { play() }
        ignoreNextCompletion = false
    }

    func setRate(_ rate: Float) {
        playbackRate = max(0.5, min(rate, 2.0))
        timePitchNode.rate = playbackRate
    }

    var duration: TimeInterval {
        guard let f = audioFile else { return 0 }
        return Double(f.length) / f.processingFormat.sampleRate
    }

    var currentTime: TimeInterval {
        guard let nodeTime = playerNode.lastRenderTime,
              let playerTime = playerNode.playerTime(forNodeTime: nodeTime) else {
            return segmentStartTime
        }
        let sampleRate = audioFile?.processingFormat.sampleRate ?? 44100
        return segmentStartTime + Double(playerTime.sampleTime) / sampleRate
    }

    var isPlaying: Bool { playerNode.isPlaying }

    // MARK: - Private

    private func scheduleFile() {
        guard let audioFile else { return }
        playerNode.scheduleFile(audioFile, at: nil) { [weak self] in
            self?.handleCompletion()
        }
    }

    private func handleCompletion() {
        guard !ignoreNextCompletion else {
            ignoreNextCompletion = false
            return
        }
        DispatchQueue.main.async { [weak self] in
            self?.stopDisplayLink()
            self?.onPlaybackFinished?()
        }
    }

    private func startDisplayLink() {
        guard displayLink == nil else { return }
        displayLink = CADisplayLink(target: self, selector: #selector(displayLinkFired))
        displayLink?.add(to: .main, forMode: .common)
    }

    private func stopDisplayLink() {
        displayLink?.invalidate()
        displayLink = nil
    }

    @objc private func displayLinkFired() {
        onTimeUpdate?(currentTime)
    }
}

enum PodcastAudioEngineError: LocalizedError {
    case invalidFile
    var errorDescription: String? { "Invalid audio file" }
}
```

- [ ] **Step 4: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "PodcastAudioEngine"`

- [ ] **Step 5: Commit**
`ios: PodcastAudioEngine — AVAudioEngine playback with rate control`

---

### Task 4: PodcastSubtitleEngine �� SRT 解析 + 時間同步

**Files:**
- Create: `ios/BooksBrowser/Services/PodcastSubtitleEngine.swift`
- Test: `ios/BooksBrowserTests/PodcastSubtitleEngineTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
import Testing
@testable import BooksBrowser

struct PodcastSubtitleEngineTests {
    static let sampleSRT = """
    1
    00:00:00,260 --> 00:00:00,440
    [Maya] <font color="#00ff00">OK so</font> here's a question that's been bugging me.

    2
    00:00:00,440 --> 00:00:00,700
    [Maya] OK so <font color="#00ff00">here's</font> a question that's been bugging me.

    3
    00:00:00,700 --> 00:00:00,880
    [Maya] OK so here's <font color="#00ff00">a</font> question that's been bugging me.

    4
    00:00:02,980 --> 00:00:03,280
    [Kai] <font color="#00ff00">And that's</font> exactly where this book starts.

    5
    00:00:03,280 --> 00:00:03,600
    [Kai] And that's <font color="#00ff00">exactly</font> where this book starts.
    """

    @Test func parsesCuesCorrectly() {
        let engine = PodcastSubtitleEngine()
        engine.load(srtContent: Self.sampleSRT)
        #expect(engine.cues.count == 5)
        #expect(engine.cues[0].speaker == "Maya")
        #expect(engine.cues[0].highlightedWord == "OK so")
        #expect(engine.cues[0].fullText == "OK so here's a question that's been bugging me.")
    }

    @Test func aggregatesSentences() {
        let engine = PodcastSubtitleEngine()
        engine.load(srtContent: Self.sampleSRT)
        #expect(engine.sentences.count == 2)
        #expect(engine.sentences[0].speaker == "Maya")
        #expect(engine.sentences[0].words.count == 3)
        #expect(engine.sentences[1].speaker == "Kai")
        #expect(engine.sentences[1].words.count == 2)
    }

    @Test func currentCueAtTime() {
        let engine = PodcastSubtitleEngine()
        engine.load(srtContent: Self.sampleSRT)
        let cue = engine.currentCue(at: 0.5)
        #expect(cue?.highlightedWord == "here's")
    }

    @Test func currentSentenceAtTime() {
        let engine = PodcastSubtitleEngine()
        engine.load(srtContent: Self.sampleSRT)
        let sentence = engine.currentSentence(at: 3.0)
        #expect(sentence?.speaker == "Kai")
    }

    @Test func stripsHtmlTags() {
        let engine = PodcastSubtitleEngine()
        engine.load(srtContent: Self.sampleSRT)
        // fullText 不含任何 HTML
        for cue in engine.cues {
            #expect(!cue.fullText.contains("<font"))
            #expect(!cue.fullText.contains("</font>"))
        }
    }

    @Test func handlesEmptyInput() {
        let engine = PodcastSubtitleEngine()
        engine.load(srtContent: "")
        #expect(engine.cues.isEmpty)
        #expect(engine.sentences.isEmpty)
        #expect(engine.currentCue(at: 0) == nil)
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "PodcastSubtitleEngine"`

- [ ] **Step 3: 實作**
```swift
import Foundation

struct PodcastSubtitleCue: Identifiable, Equatable {
    let id: Int
    let startTime: TimeInterval
    let endTime: TimeInterval
    let speaker: String
    let fullText: String
    let highlightedWord: String?
}

struct PodcastSentence: Identifiable, Equatable {
    let id: Int
    let speaker: String
    let text: String
    let startTime: TimeInterval
    let endTime: TimeInterval
    let words: [PodcastSubtitleCue]
}

final class PodcastSubtitleEngine {
    private(set) var cues: [PodcastSubtitleCue] = []
    private(set) var sentences: [PodcastSentence] = []

    private static let speakerRegex = /^\[(\w+)\]\s*/
    private static let fontTagRegex = /<font[^>]*>(.*?)<\/font>/

    func load(srtContent: String) {
        cues = parseCues(from: srtContent)
        sentences = aggregateSentences(from: cues)
    }

    func currentCue(at time: TimeInterval) -> PodcastSubtitleCue? {
        // Binary search for efficiency with large SRT files
        var lo = 0, hi = cues.count - 1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if cues[mid].endTime < time {
                lo = mid + 1
            } else if cues[mid].startTime > time {
                hi = mid - 1
            } else {
                return cues[mid]
            }
        }
        return nil
    }

    func currentSentence(at time: TimeInterval) -> PodcastSentence? {
        sentences.last { $0.startTime <= time && time <= $0.endTime }
    }

    // MARK: - Parsing

    private func parseCues(from content: String) -> [PodcastSubtitleCue] {
        let blocks = content.components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        var result: [PodcastSubtitleCue] = []

        for block in blocks {
            let lines = block.components(separatedBy: .newlines)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }

            guard lines.count >= 3,
                  let id = Int(lines[0]),
                  let (start, end) = parseTimeRange(lines[1]) else { continue }

            let rawText = lines[2...].joined(separator: " ")

            // Extract speaker
            let speaker: String
            let textAfterSpeaker: String
            if let match = rawText.firstMatch(of: Self.speakerRegex) {
                speaker = String(match.1)
                textAfterSpeaker = String(rawText[match.range.upperBound...])
            } else {
                speaker = ""
                textAfterSpeaker = rawText
            }

            // Extract highlighted word
            let highlightedWord: String?
            if let match = textAfterSpeaker.firstMatch(of: Self.fontTagRegex) {
                highlightedWord = String(match.1)
            } else {
                highlightedWord = nil
            }

            // Strip all HTML
            let fullText = textAfterSpeaker
                .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
                .trimmingCharacters(in: .whitespaces)

            result.append(PodcastSubtitleCue(
                id: id,
                startTime: start,
                endTime: end,
                speaker: speaker,
                fullText: fullText,
                highlightedWord: highlightedWord
            ))
        }

        return result.sorted { $0.startTime < $1.startTime }
    }

    private func aggregateSentences(from cues: [PodcastSubtitleCue]) -> [PodcastSentence] {
        guard !cues.isEmpty else { return [] }
        var sentences: [PodcastSentence] = []
        var currentGroup: [PodcastSubtitleCue] = [cues[0]]

        for i in 1..<cues.count {
            let cue = cues[i]
            let prev = currentGroup[0]
            // Same sentence = same speaker + same fullText
            if cue.speaker == prev.speaker && cue.fullText == prev.fullText {
                currentGroup.append(cue)
            } else {
                sentences.append(makeSentence(from: currentGroup, id: sentences.count))
                currentGroup = [cue]
            }
        }
        if !currentGroup.isEmpty {
            sentences.append(makeSentence(from: currentGroup, id: sentences.count))
        }
        return sentences
    }

    private func makeSentence(from cues: [PodcastSubtitleCue], id: Int) -> PodcastSentence {
        PodcastSentence(
            id: id,
            speaker: cues[0].speaker,
            text: cues[0].fullText,
            startTime: cues[0].startTime,
            endTime: cues.last!.endTime,
            words: cues
        )
    }

    private func parseTimeRange(_ line: String) -> (TimeInterval, TimeInterval)? {
        let parts = line.components(separatedBy: " --> ")
        guard parts.count == 2,
              let start = parseTimestamp(parts[0]),
              let end = parseTimestamp(parts[1]) else { return nil }
        return (start, end)
    }

    private func parseTimestamp(_ ts: String) -> TimeInterval? {
        let c = ts.components(separatedBy: CharacterSet(charactersIn: ":,"))
        guard c.count == 4,
              let h = Double(c[0]), let m = Double(c[1]),
              let s = Double(c[2]), let ms = Double(c[3]) else { return nil }
        return h * 3600 + m * 60 + s + ms / 1000
    }
}
```

- [ ] **Step 4: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "PodcastSubtitleEngine"`

- [ ] **Step 5: Commit**
`ios: PodcastSubtitleEngine — SRT parser with speaker tags + sentence aggregation`

---

### Task 5: PodcastPlayerViewModel — 狀態管理

**Files:**
- Create: `ios/BooksBrowser/Views/Podcast/PodcastPlayerViewModel.swift`
- Test: `ios/BooksBrowserTests/PodcastPlayerViewModelTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
import Testing
@testable import BooksBrowser

@MainActor
struct PodcastPlayerViewModelTests {
    @Test func initialState() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        #expect(vm.state == .idle)
        #expect(vm.currentTime == 0)
        #expect(vm.playbackRate == 1.0)
        #expect(vm.displayMode == .wordLevel)
    }

    @Test func setDisplayModeToggle() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        vm.setDisplayMode(.sentenceLevel)
        #expect(vm.displayMode == .sentenceLevel)
        vm.setDisplayMode(.wordLevel)
        #expect(vm.displayMode == .wordLevel)
    }

    @Test func cycleRateWrapsAround() {
        let vm = PodcastPlayerViewModel(hostNames: ["Maya", "Kai"])
        #expect(vm.playbackRate == 1.0)
        vm.cycleRate()  // → 1.25
        #expect(abs(vm.playbackRate - 1.25) < 0.01)
        vm.cycleRate()  // → 1.5
        vm.cycleRate()  // → 2.0
        vm.cycleRate()  // → 0.5
        #expect(abs(vm.playbackRate - 0.5) < 0.01)
    }
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "PodcastPlayerViewModel"`

- [ ] **Step 3: 實作**
```swift
import Foundation
import Observation

enum PodcastPlayerState: Equatable {
    case idle
    case loading
    case ready
    case playing
    case paused
    case error(String)
}

enum PodcastSubtitleDisplayMode {
    case wordLevel
    case sentenceLevel
}

@MainActor @Observable
final class PodcastPlayerViewModel {
    private(set) var state: PodcastPlayerState = .idle
    private(set) var currentTime: TimeInterval = 0
    private(set) var duration: TimeInterval = 0
    private(set) var currentSentence: PodcastSentence?
    private(set) var currentCue: PodcastSubtitleCue?
    private(set) var playbackRate: Float = 1.0
    private(set) var displayMode: PodcastSubtitleDisplayMode = .wordLevel
    let hostNames: [String]

    // Translation
    var activeWordSelection: (word: String, context: String)?

    @ObservationIgnored
    private let audioEngine = PodcastAudioEngine()
    @ObservationIgnored
    private let subtitleEngine = PodcastSubtitleEngine()

    init(hostNames: [String]) {
        self.hostNames = hostNames
        audioEngine.onTimeUpdate = { [weak self] time in
            MainActor.assumeIsolated {
                self?.handleTimeUpdate(time)
            }
        }
        audioEngine.onPlaybackFinished = { [weak self] in
            MainActor.assumeIsolated {
                self?.state = .ready
            }
        }
    }

    // MARK: - Loading

    func loadEpisode(audioURL: URL, subtitleContent: String?) {
        state = .loading
        do {
            try audioEngine.loadAudio(url: audioURL)
            duration = audioEngine.duration
            if let srt = subtitleContent {
                subtitleEngine.load(srtContent: srt)
            }
            state = .ready
        } catch {
            state = .error(error.localizedDescription)
        }
    }

    // MARK: - Playback Controls

    func play() {
        audioEngine.play()
        state = .playing
    }

    func pause() {
        audioEngine.pause()
        state = .paused
    }

    func togglePlayPause() {
        if state == .playing { pause() } else { play() }
    }

    func seek(to time: TimeInterval) {
        let shouldResume = state == .playing
        audioEngine.seek(to: time, autoResume: shouldResume)
        handleTimeUpdate(time)
    }

    func skip(seconds: Double) {
        let target = max(0, min(duration, currentTime + seconds))
        seek(to: target)
    }

    func cycleRate() {
        let next = PodcastAudioEngine.nextRate(after: playbackRate)
        playbackRate = next
        audioEngine.setRate(next)
    }

    func setDisplayMode(_ mode: PodcastSubtitleDisplayMode) {
        displayMode = mode
    }

    // MARK: - Word Tap

    func handleWordTap(word: String, context: String) {
        activeWordSelection = (word, context)
    }

    func dismissWordSelection() {
        activeWordSelection = nil
    }

    // MARK: - Computed

    var visibleSentences: [PodcastSentence] {
        subtitleEngine.sentences
    }

    var rateDisplayText: String {
        String(format: "×%.2g", playbackRate)
    }

    // MARK: - Private

    private func handleTimeUpdate(_ time: TimeInterval) {
        currentTime = time
        currentCue = subtitleEngine.currentCue(at: time)
        currentSentence = subtitleEngine.currentSentence(at: time)
    }
}
```

- [ ] **Step 4: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "PodcastPlayerViewModel"`

- [ ] **Step 5: Commit**
`ios: PodcastPlayerViewModel — playback state management`

---

### Task 6: 播放器 UI — PodcastPlayerView + PodcastControlsView

> **TDD 備註：** Tasks 6-8 為純 View 層，不含可獨立測試的業務邏輯（已在 Task 3-5 測過）。以 `#Preview` 驗證外觀，build 確認編譯通過。

**Files:**
- Create: `ios/BooksBrowser/Views/Podcast/PodcastPlayerView.swift`
- Create: `ios/BooksBrowser/Views/Podcast/PodcastControlsView.swift`

- [ ] **Step 1: 實作 PodcastControlsView**
```swift
import SwiftUI

struct PodcastControlsView: View {
    let viewModel: PodcastPlayerViewModel
    @Environment(\.vocabSkin) private var skin

    @State private var isDragging = false
    @State private var dragTime: TimeInterval = 0

    var body: some View {
        VStack(spacing: skin.spacing.sectionGap) {
            // Seek bar
            seekBar
            // Time labels
            HStack {
                Text(formatTime(activeTime))
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(skin.palette.tertiaryText)
                Spacer()
                Text(formatTime(viewModel.duration))
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(skin.palette.tertiaryText)
            }
            // Transport controls
            HStack(spacing: skin.spacing.controlGap) {
                Button { viewModel.skip(seconds: -15) } label: {
                    Image(systemName: "gobackward.15")
                        .font(.system(size: 28))
                }
                Button { viewModel.togglePlayPause() } label: {
                    Image(systemName: viewModel.state == .playing ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 56))
                }
                Button { viewModel.skip(seconds: 15) } label: {
                    Image(systemName: "goforward.15")
                        .font(.system(size: 28))
                }
            }
            .foregroundStyle(skin.palette.accent)
            // Bottom bar: mode toggle + rate
            HStack {
                // Display mode picker
                HStack(spacing: 0) {
                    modeButton("W", mode: .wordLevel)
                    modeButton("S", mode: .sentenceLevel)
                }
                .background(skin.palette.mutedFill, in: Capsule())
                Spacer()
                // Rate chip
                Button { viewModel.cycleRate() } label: {
                    Text(viewModel.rateDisplayText)
                        .font(skin.typography.monoLabel)
                        .padding(.horizontal, skin.spacing.chipHorizontalPadding)
                        .padding(.vertical, skin.spacing.chipVerticalPadding)
                        .background(skin.palette.mutedFill, in: Capsule())
                }
                .foregroundStyle(skin.palette.primaryText)
            }
        }
    }

    private var activeTime: TimeInterval {
        isDragging ? dragTime : viewModel.currentTime
    }

    @ViewBuilder
    private var seekBar: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack(alignment: .leading) {
                Capsule().fill(skin.palette.progressBarBackground).frame(height: 5)
                Capsule().fill(skin.palette.accent)
                    .frame(width: progressWidth(in: w), height: 5)
                Circle().fill(skin.palette.cardBackground)
                    .frame(width: 16, height: 16)
                    .shadow(color: skin.palette.shadow.opacity(0.15), radius: 4, y: 2)
                    .offset(x: max(0, progressWidth(in: w) - 8))
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { v in
                                isDragging = true
                                dragTime = max(0, min(viewModel.duration, Double(v.location.x / w) * viewModel.duration))
                            }
                            .onEnded { _ in
                                isDragging = false
                                viewModel.seek(to: dragTime)
                            }
                    )
            }
        }
        .frame(height: 20)
        .animation(AppMotion.swipeTrackingSpring, value: isDragging)
    }

    private func progressWidth(in totalWidth: CGFloat) -> CGFloat {
        guard viewModel.duration > 0 else { return 0 }
        return CGFloat(activeTime / viewModel.duration) * totalWidth
    }

    @ViewBuilder
    private func modeButton(_ label: String, mode: PodcastSubtitleDisplayMode) -> some View {
        Button {
            withAnimation(AppMotion.standardSpring) {
                viewModel.setDisplayMode(mode)
            }
        } label: {
            Text(label)
                .font(skin.typography.monoLabel)
                .padding(.horizontal, skin.spacing.chipHorizontalPadding)
                .padding(.vertical, skin.spacing.chipVerticalPadding)
                .background(
                    viewModel.displayMode == mode
                        ? skin.palette.accent.opacity(0.15)
                        : Color.clear,
                    in: Capsule()
                )
        }
        .foregroundStyle(
            viewModel.displayMode == mode
                ? skin.palette.accent
                : skin.palette.tertiaryText
        )
    }

    private func formatTime(_ t: TimeInterval) -> String {
        guard t.isFinite, !t.isNaN else { return "--:--" }
        let m = Int(t) / 60, s = Int(t) % 60
        return String(format: "%02d:%02d", m, s)
    }
}
```

- [ ] **Step 2: 實作 PodcastPlayerView**
```swift
import SwiftUI

struct PodcastPlayerView: View {
    let episodeId: String
    @Environment(\.vocabSkin) private var skin
    @Environment(\.appTheme) private var theme
    @Environment(\.modelContext) private var modelContext

    @State private var viewModel: PodcastPlayerViewModel?

    var body: some View {
        Group {
            if let vm = viewModel {
                playerContent(vm)
            } else {
                ProgressView("載入中…")
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .task { await loadEpisode() }
    }

    @ViewBuilder
    private func playerContent(_ vm: PodcastPlayerViewModel) -> some View {
        switch vm.state {
        case .idle, .loading:
            VStack(spacing: skin.spacing.sectionGap) {
                ProgressView()
                Text("載入音訊…")
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .error(let msg):
            VStack(spacing: skin.spacing.sectionGap) {
                Image(systemName: "xmark.octagon")
                    .font(.largeTitle)
                    .foregroundStyle(skin.palette.destructive)
                Text("音訊載入失敗")
                    .font(skin.typography.sectionTitle)
                Text(msg)
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                Button("重試") { Task { await loadEpisode() } }
                    .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .ready, .playing, .paused:
            VStack(spacing: 0) {
                // Subtitle area
                PodcastSubtitleView(viewModel: vm)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

                // Controls
                PodcastControlsView(viewModel: vm)
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                    .padding(.bottom, AppShellMetrics.pageBottomPadding)
            }
            .background(theme.palette.pageBackground)
        }
    }

    private func loadEpisode() async {
        // Fetch episode from SwiftData
        let descriptor = FetchDescriptor<PodcastEpisode>(
            predicate: #Predicate { $0.remoteId == episodeId }
        )
        guard let episode = try? modelContext.fetch(descriptor).first,
              let series = episode.series else { return }

        let vm = PodcastPlayerViewModel(hostNames: series.hostNames)
        viewModel = vm

        // Load audio from local path or bundle
        guard let audioPath = episode.localAudioPath,
              let audioURL = URL(string: audioPath) else {
            vm.state = .error("音訊檔案不存在")
            return
        }

        let subtitleContent: String?
        if let srtPath = episode.localSubtitlePath {
            subtitleContent = try? String(contentsOf: URL(string: srtPath)!, encoding: .utf8)
        } else {
            subtitleContent = nil
        }

        vm.loadEpisode(audioURL: audioURL, subtitleContent: subtitleContent)
    }
}
```

- [ ] **Step 3: Preview 驗證**
為兩個 View 加 `#Preview` 確認外觀。

- [ ] **Step 4: Commit**
`ios: PodcastPlayerView + PodcastControlsView — player UI with seek, skip, rate`

---

### Task 7: 雙人字幕 UI — SpeakerAccentBar + WordLevel + SentenceLevel

**Files:**
- Create: `ios/BooksBrowser/Views/Podcast/SpeakerAccentBar.swift`
- Create: `ios/BooksBrowser/Views/Podcast/PodcastSubtitleView.swift`
- Create: `ios/BooksBrowser/Views/Podcast/PodcastWordLevelView.swift`
- Create: `ios/BooksBrowser/Views/Podcast/PodcastSentenceLevelView.swift`

- [ ] **Step 1: 實作 SpeakerAccentBar**
```swift
import SwiftUI

struct SpeakerAccentBar: View {
    let speaker: String
    let hostNames: [String]
    @Environment(\.vocabSkin) private var skin

    private var barColor: Color {
        guard let index = hostNames.firstIndex(of: speaker) else {
            return skin.palette.primaryTextMuted
        }
        return index == 0 ? skin.palette.accent : skin.palette.success
    }

    var body: some View {
        RoundedRectangle(cornerRadius: skin.radii.tiny)
            .fill(barColor)
            .frame(width: 3)
    }
}

struct SpeakerChip: View {
    let speaker: String
    let hostNames: [String]
    @Environment(\.vocabSkin) private var skin

    private var chipColor: Color {
        guard let index = hostNames.firstIndex(of: speaker) else {
            return skin.palette.primaryTextMuted
        }
        return index == 0 ? skin.palette.accent : skin.palette.success
    }

    var body: some View {
        Text(speaker)
            .font(skin.typography.monoLabel)
            .foregroundStyle(chipColor)
            .padding(.horizontal, skin.spacing.chipHorizontalPadding)
            .padding(.vertical, skin.spacing.chipVerticalPadding / 2)
            .background(chipColor.opacity(0.12), in: Capsule())
    }
}
```

- [ ] **Step 2: 實作 PodcastWordLevelView**
```swift
import SwiftUI

struct PodcastWordLevelView: View {
    let sentence: PodcastSentence?
    let currentCue: PodcastSubtitleCue?
    let hostNames: [String]
    let onWordTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        if let sentence {
            HStack(alignment: .top, spacing: skin.spacing.inlineGap) {
                SpeakerAccentBar(speaker: sentence.speaker, hostNames: hostNames)
                VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                    SpeakerChip(speaker: sentence.speaker, hostNames: hostNames)
                    wordFlowLayout(sentence: sentence)
                }
            }
            .padding(skin.spacing.cardPadding)
            .background(skin.palette.cardBackground, in: RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
            .animation(AppMotion.contentReveal, value: sentence.id)
        } else {
            Text("—")
                .font(skin.typography.body)
                .foregroundStyle(skin.palette.tertiaryText)
                .frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func wordFlowLayout(sentence: PodcastSentence) -> some View {
        // Split sentence text into tappable words
        let words = sentence.text.split(separator: " ").map(String.init)
        FlowLayout(spacing: 4) {
            ForEach(Array(words.enumerated()), id: \.offset) { _, word in
                let isHighlighted = currentCue?.highlightedWord?.contains(word) == true
                    || word == currentCue?.highlightedWord
                Text(word)
                    .font(skin.typography.body)
                    .foregroundStyle(isHighlighted ? skin.palette.cardBackground : skin.palette.primaryText)
                    .padding(.horizontal, 2)
                    .padding(.vertical, 1)
                    .background(
                        isHighlighted
                            ? skin.palette.accent
                            : Color.clear,
                        in: RoundedRectangle(cornerRadius: 4, style: .continuous)
                    )
                    .animation(AppMotion.feedbackPulse, value: isHighlighted)
                    .onTapGesture {
                        onWordTap(word, sentence.text)
                    }
            }
        }
    }
}

/// Simple flow layout for wrapping words
struct FlowLayout: Layout {
    let spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = computeLayout(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = computeLayout(proposal: proposal, subviews: subviews)
        for (index, offset) in result.offsets.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + offset.x, y: bounds.minY + offset.y), proposal: .unspecified)
        }
    }

    private struct LayoutResult {
        var size: CGSize
        var offsets: [CGPoint]
    }

    private func computeLayout(proposal: ProposedViewSize, subviews: Subviews) -> LayoutResult {
        let maxWidth = proposal.width ?? .infinity
        var offsets: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var maxX: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            offsets.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            maxX = max(maxX, x)
        }

        return LayoutResult(
            size: CGSize(width: maxX, height: y + rowHeight),
            offsets: offsets
        )
    }
}
```

- [ ] **Step 3: 實作 PodcastSentenceLevelView**
```swift
import SwiftUI

struct PodcastSentenceLevelView: View {
    let sentences: [PodcastSentence]
    let currentSentenceId: Int?
    let hostNames: [String]
    let onSentenceTap: (PodcastSentence) -> Void
    let onWordTap: (String, String) -> Void
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: skin.spacing.wordRowVerticalGap) {
                    ForEach(sentences) { sentence in
                        let isCurrent = sentence.id == currentSentenceId
                        sentenceRow(sentence, isCurrent: isCurrent)
                            .id(sentence.id)
                            .opacity(isCurrent ? 1.0 : 0.4)
                            .animation(AppMotion.contentFade, value: isCurrent)
                            .onTapGesture {
                                if !isCurrent { onSentenceTap(sentence) }
                            }
                    }
                }
                .padding(.vertical, skin.spacing.sectionGap)
            }
            .onChange(of: currentSentenceId) { _, newId in
                guard let newId else { return }
                withAnimation(AppMotion.standardSpring) {
                    proxy.scrollTo(newId, anchor: .center)
                }
            }
        }
    }

    @ViewBuilder
    private func sentenceRow(_ sentence: PodcastSentence, isCurrent: Bool) -> some View {
        HStack(alignment: .top, spacing: skin.spacing.inlineGap) {
            SpeakerAccentBar(speaker: sentence.speaker, hostNames: hostNames)
            VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                SpeakerChip(speaker: sentence.speaker, hostNames: hostNames)
                if isCurrent {
                    tappableText(sentence)
                } else {
                    Text(sentence.text)
                        .font(skin.typography.body)
                        .foregroundStyle(skin.palette.primaryText)
                }
            }
        }
        .padding(skin.spacing.cardPadding)
        .background(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .fill(isCurrent ? skin.palette.cardBackground : Color.clear)
        )
    }

    @ViewBuilder
    private func tappableText(_ sentence: PodcastSentence) -> some View {
        let words = sentence.text.split(separator: " ").map(String.init)
        FlowLayout(spacing: 4) {
            ForEach(Array(words.enumerated()), id: \.offset) { _, word in
                Text(word)
                    .font(skin.typography.body)
                    .foregroundStyle(skin.palette.primaryText)
                    .onTapGesture { onWordTap(word, sentence.text) }
            }
        }
    }
}
```

- [ ] **Step 4: 實作 PodcastSubtitleView 容器**
```swift
import SwiftUI

struct PodcastSubtitleView: View {
    let viewModel: PodcastPlayerViewModel
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        Group {
            switch viewModel.displayMode {
            case .wordLevel:
                PodcastWordLevelView(
                    sentence: viewModel.currentSentence,
                    currentCue: viewModel.currentCue,
                    hostNames: viewModel.hostNames,
                    onWordTap: viewModel.handleWordTap
                )
                .frame(maxHeight: .infinity)
            case .sentenceLevel:
                PodcastSentenceLevelView(
                    sentences: viewModel.visibleSentences,
                    currentSentenceId: viewModel.currentSentence?.id,
                    hostNames: viewModel.hostNames,
                    onSentenceTap: { viewModel.seek(to: $0.startTime) },
                    onWordTap: viewModel.handleWordTap
                )
            }
        }
    }
}
```

- [ ] **Step 5: Preview 驗證**
各 View 加 `#Preview`，用 mock `PodcastSentence` / `PodcastSubtitleCue` 資料。

- [ ] **Step 6: Commit**
`ios: dual-speaker subtitle UI — accent bar, word-level highlight, sentence scroll`

---

### Task 8: 集數列表 — PodcastEpisodeListView

**Files:**
- Create: `ios/BooksBrowser/Views/Podcast/PodcastEpisodeListView.swift`
- Create: `ios/BooksBrowser/Views/Podcast/PodcastEpisodeRow.swift`

- [ ] **Step 1: 實作 PodcastEpisodeRow**
```swift
import SwiftUI

struct PodcastEpisodeRow: View {
    let episode: PodcastEpisode
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        VStack(alignment: .leading, spacing: skin.spacing.rowContentSpacing) {
            Text(episode.displayTitle)
                .font(skin.typography.sectionTitle)
                .foregroundStyle(skin.palette.primaryText)
                .lineLimit(2)

            HStack(spacing: skin.spacing.metadataGap) {
                Text(formatDuration(episode.durationSec))
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(skin.palette.tertiaryText)

                if episode.audioAvailable {
                    Image(systemName: "waveform.circle.fill")
                        .font(.caption)
                        .foregroundStyle(skin.palette.accent)
                }
                if episode.subtitleAvailable {
                    Image(systemName: "captions.bubble.fill")
                        .font(.caption)
                        .foregroundStyle(skin.palette.success)
                }
            }
        }
        .padding(.vertical, skin.spacing.compactRowVerticalPadding)
    }

    private func formatDuration(_ sec: Double) -> String {
        let m = Int(sec) / 60, s = Int(sec) % 60
        return String(format: "%d:%02d", m, s)
    }
}
```

- [ ] **Step 2: 實作 PodcastEpisodeListView**
```swift
import SwiftUI
import SwiftData

struct PodcastEpisodeDestination: Hashable {
    let episodeId: String
}

struct PodcastEpisodeListView: View {
    let seriesId: String
    @Environment(\.vocabSkin) private var skin
    @Environment(\.appTheme) private var theme
    @Environment(\.modelContext) private var modelContext

    @Query private var allEpisodes: [PodcastEpisode]

    init(seriesId: String) {
        self.seriesId = seriesId
        // SwiftData @Query doesn't support relationship predicates,
        // so we fetch all and filter in computed property
        _allEpisodes = Query(sort: \.episodeNumber)
    }

    private var episodes: [PodcastEpisode] {
        allEpisodes.filter { $0.series?.remoteId == seriesId }
    }

    private var seriesTitle: String {
        episodes.first?.series?.title ?? ""
    }

    var body: some View {
        Group {
            if episodes.isEmpty {
                VStack(spacing: skin.spacing.sectionGap) {
                    Image(systemName: "waveform")
                        .font(.largeTitle)
                        .foregroundStyle(skin.palette.tertiaryText)
                    Text("尚無集數")
                        .font(skin.typography.sectionTitle)
                        .foregroundStyle(skin.palette.secondaryText)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(episodes) { episode in
                        NavigationLink(value: PodcastEpisodeDestination(episodeId: episode.remoteId)) {
                            PodcastEpisodeRow(episode: episode)
                        }
                        .disabled(!episode.audioAvailable)
                    }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle(seriesTitle)
        .navigationDestination(for: PodcastEpisodeDestination.self) { dest in
            PodcastPlayerView(episodeId: dest.episodeId)
        }
    }
}
```

- [ ] **Step 3: Preview 驗證**

- [ ] **Step 4: Commit**
`ios: PodcastEpisodeListView — episode list with availability badges`

---

### Task 9: 單字查詢整合 — PodcastTranslationHandler

**Files:**
- Create: `ios/BooksBrowser/Views/Podcast/PodcastTranslationHandler.swift`
- Modify: `ios/BooksBrowser/Views/Podcast/PodcastPlayerView.swift` (加 TranslationPanel overlay)
- Test: `ios/BooksBrowserTests/PodcastTranslationHandlerTests.swift`

- [ ] **Step 1: 寫 failing test**
```swift
import Testing
@testable import BooksBrowser

@MainActor
struct PodcastTranslationHandlerTests {
    @Test func handleWordTapSetsSelection() async {
        let mockTranslation = MockTranslating()
        let handler = PodcastTranslationHandler(translationService: mockTranslation)
        await handler.handleWordTap(word: "bugging", context: "OK so here's a question that's been bugging me.")
        #expect(handler.wordSelection?.word == "bugging")
        #expect(handler.isTranslating || handler.translationResult != nil)
    }

    @Test func dismissClearsState() async {
        let handler = PodcastTranslationHandler(translationService: MockTranslating())
        await handler.handleWordTap(word: "test", context: "test context")
        handler.dismiss()
        #expect(handler.wordSelection == nil)
        #expect(handler.translationResult == nil)
    }
}

private class MockTranslating: Translating {
    func translateQuick(word: String, context: String, onRetry: ((Int, Int) -> Void)?) async throws -> TranslationResult {
        TranslationResult(translation: "mock", partOfSpeech: "v.", explanation: nil, rootForm: nil, latency: 0.1)
    }
    func translatePhrase(phrase: String, context: String, onRetry: ((Int, Int) -> Void)?) async throws -> String { "mock" }
    func fetchExplanation(word: String, context: String, onRetry: ((Int, Int) -> Void)?) async throws -> (explanation: String, latency: TimeInterval) { ("mock", 0.1) }
}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `./ops/ios_test.sh -g "PodcastTranslationHandler"`

- [ ] **Step 3: 實作 PodcastTranslationHandler**
```swift
import Foundation
import Observation

@MainActor @Observable
final class PodcastTranslationHandler {
    var wordSelection: WordSelection?
    var translationResult: TranslationResult?
    var isTranslating: Bool = false
    var isSaved: Bool = false
    var translationErrorMessage: String?

    @ObservationIgnored
    private let translationService: any Translating
    @ObservationIgnored
    private var currentTask: Task<Void, Never>?

    init(translationService: any Translating = TranslationService()) {
        self.translationService = translationService
    }

    func handleWordTap(word: String, context: String) async {
        let normalized = word
            .trimmingCharacters(in: .punctuationCharacters.union(.symbols))
            .lowercased()
        guard !normalized.isEmpty else { return }

        currentTask?.cancel()
        wordSelection = WordSelection(word: normalized, context: context, position: .zero)
        translationResult = nil
        translationErrorMessage = nil
        isTranslating = true
        isSaved = false

        currentTask = Task {
            do {
                let result = try await translationService.translateQuick(
                    word: normalized,
                    context: context,
                    onRetry: nil
                )
                guard !Task.isCancelled else { return }
                translationResult = result
                isTranslating = false
                // TODO: auto-save to vocabulary in future iteration
            } catch {
                guard !Task.isCancelled else { return }
                isTranslating = false
                translationErrorMessage = error.localizedDescription
            }
        }
    }

    func dismiss() {
        currentTask?.cancel()
        wordSelection = nil
        translationResult = nil
        isTranslating = false
        isSaved = false
        translationErrorMessage = nil
    }
}
```

- [ ] **Step 4: PodcastPlayerView 加 TranslationPanel overlay**
在 `playerContent` 的 `.ready/.playing/.paused` case 加入：
```swift
.overlay(alignment: .bottom) {
    if let handler = translationHandler, handler.wordSelection != nil {
        TranslationPanel(
            word: handler.wordSelection!.word,
            result: handler.translationResult,
            isLoading: handler.isTranslating,
            isSaved: handler.isSaved,
            isLoggedIn: true,
            isExpanded: false,
            explanation: nil,
            isLoadingExplanation: false,
            statusMessage: nil,
            isExplanationOnly: false,
            translationErrorMessage: handler.translationErrorMessage,
            explanationErrorMessage: nil,
            onExpand: {},
            onDelete: {},
            onShowDetail: nil,
            onDismiss: { handler.dismiss() }
        )
        .transition(.readerPanelReveal)
    }
}
```

也需把 `PodcastPlayerViewModel.handleWordTap` 改為呼叫 `translationHandler`。

- [ ] **Step 5: 跑 test 確認通過**
Run: `./ops/ios_test.sh -g "PodcastTranslationHandler"`

- [ ] **Step 6: Commit**
`ios: PodcastTranslationHandler — word tap → translation panel integration`

---

### Task 10: Debug Seed Data + 整合測試

**Files:**
- Create: `ios/BooksBrowser/Services/PodcastDebugSeed.swift`
- Bundle: `ios/BooksBrowserTests/Resources/test_podcast_clip.mp3`
- Bundle: `ios/BooksBrowserTests/Resources/test_podcast_clip.srt`

- [ ] **Step 1: 準備測試資源**
```bash
# 截取前 30 秒音訊
ffmpeg -i lab/podcast/workspaces/flow_950f1a7d/scripts/ep_1_pro.mp3 \
  -t 30 -c copy ios/BooksBrowser/Resources/debug_podcast.mp3

# 截取對應 SRT（前 30 秒的 cues）
head -200 lab/podcast/workspaces/flow_950f1a7d/scripts/ep_1_pro.srt \
  > ios/BooksBrowser/Resources/debug_podcast.srt
```

- [ ] **Step 2: 實作 PodcastDebugSeed**
```swift
#if DEBUG
import SwiftData

enum PodcastDebugSeed {
    @MainActor
    static func seedIfNeeded(context: ModelContext) {
        let descriptor = FetchDescriptor<PodcastSeries>()
        guard (try? context.fetchCount(descriptor)) == 0 else { return }

        let series = PodcastSeries(
            remoteId: "debug-flow",
            title: "Flow: The Psychology of Optimal Experience",
            hostNames: ["Maya", "Kai"]
        )
        series.color = "#5B8C5A"
        series.coverPattern = "waves"
        series.episodeCount = 1
        series.totalDurationSec = 30
        context.insert(series)

        let episode = PodcastEpisode(
            remoteId: "debug-flow-ep1",
            episodeNumber: 1,
            title: "The Happiness Trap",
            durationSec: 30
        )
        episode.series = series
        episode.audioAvailable = true
        episode.subtitleAvailable = true
        // Point to bundled resources
        if let audioURL = Bundle.main.url(forResource: "debug_podcast", withExtension: "mp3") {
            episode.localAudioPath = audioURL.absoluteString
        }
        if let srtURL = Bundle.main.url(forResource: "debug_podcast", withExtension: "srt") {
            episode.localSubtitlePath = srtURL.absoluteString
        }
        context.insert(episode)

        try? context.save()
    }
}
#endif
```

- [ ] **Step 3: 在 BooksBrowserApp 呼叫 seed**
```swift
#if DEBUG
PodcastDebugSeed.seedIfNeeded(context: modelContainer.mainContext)
#endif
```

- [ ] **Step 4: 端對端驗證**
1. Build app
2. 書架應顯示一個帶 waveform badge 的 podcast 卡片
3. 點擊 → 集數列表 → 點擊 Episode 1
4. 播放器載入音訊，字幕逐詞高亮
5. 切換 word/sentence 模式
6. 點擊單字 → TranslationPanel 出現
7. 變速 → 音訊速度改變

- [ ] **Step 5: Commit**
`ios: podcast debug seed + bundle test assets for end-to-end testing`
