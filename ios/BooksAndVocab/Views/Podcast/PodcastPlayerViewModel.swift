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

enum PodcastPlayerBootstrapPhase: Equatable {
    case loading
    case missingEpisode
    case ready

    static func phase(
        hasViewModel: Bool,
        loadAttempted: Bool,
        hasEpisode: Bool,
        hasSeries: Bool
    ) -> PodcastPlayerBootstrapPhase {
        if hasViewModel { return .ready }
        if loadAttempted && (!hasEpisode || !hasSeries) { return .missingEpisode }
        return .loading
    }
}

/// Lifecycle of the subtitle (SRT) load, tracked separately from audio.
///
/// A failed subtitle fetch used to be swallowed by `try?` — audio kept
/// playing while subtitles were permanently missing with no prompt. This
/// state lets the player surface an inline "字幕載入失敗 ⟳" retry without
/// interrupting playback.
///
/// `.idle` = not yet started (transient pre-load); `.unavailable` = the
/// episode genuinely ships no subtitle URL, surfaced as an explicit hint so
/// users aren't left guessing why the bubble layer is empty (track-3 state
/// matrix L407/L410 — previously `.loading` and "unavailable" both rendered
/// no overlay and looked identical).
enum PodcastSubtitleLoadState: Equatable {
    case idle
    case loading
    case loaded
    case failed
    case unavailable
}

enum SleepTimerMode: Hashable {
    case off
    case minutes(Int)
    case endOfEpisode
}

@MainActor @Observable
final class PodcastPlayerViewModel {
    private(set) var state: PodcastPlayerState = .idle
    private(set) var currentTime: TimeInterval = 0
    private(set) var duration: TimeInterval = 0
    /// Furthest absolute time AVPlayer has buffered (seconds). Drives the
    /// "已載入" overlay on the seek bar. 0 until the first range arrives.
    private(set) var bufferedEnd: TimeInterval = 0
    private(set) var currentSentence: PodcastSentence?
    /// 首次進場用的播放位置是否已 bootstrap。只管「初始化是否已經決定」，
    /// 不代表正在播放或已持久化；用途是避免 view 在未知位置先顯示頂部狀態。
    private(set) var initialPositionResolved: Bool = false
    /// Sentence id the auto-follow scroll targets — leads `currentSentence` by
    /// `scrollLeadSec` on natural ticks so the next bubble reaches viewport center
    /// just before it's spoken; pinned to the current sentence on a seek (★B1). The
    /// View drives `followScroll` off THIS, not `currentSentence`, while highlight /
    /// underline stay keyed on the precise `currentSentence` — so the scroll leads
    /// but the highlight never does.
    private(set) var scrollLeadSentenceId: Int?
    private(set) var renderState: SubtitleRenderState?
    /// Anchor for extrapolating a continuous playhead between 15 Hz ticks (see
    /// `PodcastPlaybackClock`). Refreshed on every tick / seek / play / pause /
    /// rate change. `wallClock` uses `Date.timeIntervalSinceReferenceDate`.
    private(set) var playbackAnchor = PlaybackAnchor(
        mediaTime: 0, wallClock: Date().timeIntervalSinceReferenceDate, rate: 0
    ) {
        didSet { liveAnchor.value = playbackAnchor }
    }
    /// Reference-typed mirror of `playbackAnchor` for the subtitle view's
    /// per-frame underline + follow offset. Kept in sync by the `didSet` above so
    /// no anchor-mutation site can forget it. See `PodcastLiveAnchor` for why the
    /// view needs a reference (Equatable-skip + live playhead). `@ObservationIgnored`
    /// because the View reads it imperatively each frame via its own TimelineView,
    /// not through `@Observable` change tracking.
    @ObservationIgnored
    let liveAnchor = PodcastLiveAnchor(
        value: PlaybackAnchor(mediaTime: 0, wallClock: Date().timeIntervalSinceReferenceDate, rate: 0)
    )
    private(set) var playbackRate: Float = 1.0
    /// Subtitle load lifecycle — drives the inline retry UI. Independent of
    /// `state` so a subtitle failure never blocks or interrupts audio.
    private(set) var subtitleState: PodcastSubtitleLoadState = .idle
    /// Sleep timer mode. UI binds via `setSleepTimer(_:)` to keep the
    /// DispatchSourceTimer schedule in sync with the published mode.
    private(set) var sleepTimerMode: SleepTimerMode = .off
    /// Absolute wall-clock deadline for `.minutes(_)` mode. nil for
    /// `.off` / `.endOfEpisode`. Drives the TimelineView countdown.
    private(set) var sleepDeadline: Date?
    /// Monotonic counter bumped each time the sleep timer fires (minutes
    /// deadline reached or end-of-episode hit). The View observes this to
    /// drive sensory feedback + toast — users otherwise see playback pause
    /// with no signal that the sleep timer caused it.
    private(set) var sleepTimerFiredTick: Int = 0
    let hostNames: [String]

    /// 播放自然結束（`AVPlayerItemDidPlayToEndTime`）的 monotonic 計數。view 以
    /// `.onChange` 觀察來驅動連續播放換集——用 counter 而非 closure，避免「VM→closure
    /// →view struct→viewModel @State box→VM」retain cycle（鏡射 `sleepTimerFiredTick`）。
    /// `.endOfEpisode` 睡眠定時觸發那次**不**遞增（用戶要求播完本集即停）。
    private(set) var episodeFinishedTick: Int = 0

    // Translation — set by the player view
    var activeWordSelection: (word: String, context: String)?
    var activePhraseSelection: (phrase: String, context: String)?
    var activeExplainSelection: (text: String, context: String)?
    // Counters tick on every tap so the View's onChange fires even when the
    // same word/phrase is tapped twice in a row (value-equal onChange is a no-op).
    private(set) var wordTapTick: Int = 0
    private(set) var phraseTapTick: Int = 0
    private(set) var explainTapTick: Int = 0

    @ObservationIgnored
    private let audioEngine = PodcastAudioEngine()
    @ObservationIgnored
    private let subtitleEngine = PodcastSubtitleEngine()
    @ObservationIgnored
    private var sleepTimerSource: DispatchSourceTimer?

    deinit {
        sleepTimerSource?.cancel()
    }

    init(hostNames: [String]) {
        self.hostNames = hostNames
        audioEngine.onTimeUpdate = { [weak self] time in
            MainActor.assumeIsolated {
                self?.handleTimeUpdate(time)
            }
        }
        audioEngine.onPlaybackFinished = { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                // DidPlayToEndTime can fire on a truncated item right after a
                // mid-stream failure already transitioned us to .error — don't
                // let it silently clobber the error UI back to .ready.
                if case .error = self.state { return }
                self.state = .ready
                if self.sleepTimerMode == .endOfEpisode {
                    self.sleepTimerMode = .off
                    self.sleepTimerFiredTick &+= 1
                    return  // 睡眠定時設「播完本集」→ 停在本集尾，不自動續播。
                }
                // 連續播放：bump tick，view 的 .onChange 評估下一集（gate 在 PodcastQueue）。
                self.episodeFinishedTick &+= 1
            }
        }
        audioEngine.onDurationLoaded = { [weak self] d in
            MainActor.assumeIsolated {
                self?.duration = d
            }
        }
        audioEngine.onBufferedEndChanged = { [weak self] end in
            MainActor.assumeIsolated {
                self?.bufferedEnd = end
            }
        }
        audioEngine.onReadyToPlay = { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                if self.state == .loading { self.state = .ready }
            }
        }
        audioEngine.onLoadFailed = { [weak self] msg in
            MainActor.assumeIsolated {
                self?.state = .error(msg)
            }
        }
        audioEngine.onSystemPause = { [weak self] in
            MainActor.assumeIsolated {
                // Keep VM state consistent with engine when the system forces
                // pause. Handle .playing AND .loading — an interruption during
                // load would otherwise leave VM stuck in .loading forever
                // because no natural .ready transition happens post-interrupt.
                guard let self else { return }
                if self.state == .playing || self.state == .loading {
                    self.state = .paused
                }
            }
        }
        audioEngine.onSystemResume = { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                if self.state == .paused { self.state = .playing }
            }
        }
    }

    // MARK: - Loading

    func loadEpisode(
        audioURL: URL,
        subtitleContent: String?,
        title: String = "",
        audioHTTPHeaders: [String: String] = [:],
        prefetchedDurationSec: TimeInterval = 0,
        initialProgressTime: TimeInterval? = nil
    ) {
        state = .loading
        currentTime = 0
        currentSentence = nil
        scrollLeadSentenceId = nil
        renderState = nil
        initialPositionResolved = false
        duration = 0
        bufferedEnd = 0
        // Register NowPlaying metadata BEFORE loadAudio: the synchronous
        // updateNowPlayingInfo() fired inside loadAudio (when prefetchedDuration
        // populates duration immediately) would otherwise read an empty title
        // for one runloop tick, briefly flashing a blank lock-screen card.
        audioEngine.configureNowPlaying(
            title: title,
            artist: hostNames.joined(separator: " & ")
        )
        audioEngine.loadAudio(
            url: audioURL,
            httpHeaders: audioHTTPHeaders,
            prefetchedDuration: prefetchedDurationSec > 0 ? prefetchedDurationSec : nil
        )
        if let srt = subtitleContent {
            applySubtitle(content: srt)
        }
        bootstrapInitialPlaybackPosition(initialProgressTime)
        // state → .ready (via onReadyToPlay) or .error (via onLoadFailed) arrives async.
    }

    // MARK: - Subtitle load lifecycle

    /// Marks the subtitle fetch as in-flight. Use before kicking off the
    /// network load and again on retry.
    func setSubtitleLoading() {
        subtitleState = .loading
    }

    /// Parses fetched SRT content into sentences. A parse that yields zero
    /// sentences (empty / whitespace-only / malformed SRT) converges to
    /// `.unavailable` rather than falsely reporting `.loaded`: an empty bubble
    /// layer under `.loaded` is indistinguishable from `.loading` and the
    /// genuine no-subtitle case, leaving the user staring at a blank void with
    /// no explanation. Routing it to `.unavailable` surfaces the existing
    /// "此集無逐句字幕" hint.
    func applySubtitle(content: String) {
        subtitleEngine.load(srtContent: content)
        subtitleState = subtitleEngine.sentences.isEmpty ? .unavailable : .loaded
        if currentTime > 0 {
            syncPlaybackPosition(currentTime, pinLead: true)
        }
    }

    /// Marks the subtitle fetch as failed — drives the inline retry UI.
    func markSubtitleFailed() {
        subtitleState = .failed
    }

    /// The episode genuinely ships no subtitle URL. Drives an explicit
    /// "此集無逐句字幕" hint so the empty bubble layer is no longer
    /// indistinguishable from `.loading` (state matrix L410).
    func markSubtitleUnavailable() {
        subtitleState = .unavailable
    }

    /// 初始化進場位置：若有中段 progress，先把 VM 的字幕 render state 與
    /// scroll target 對齊，並同步讓底層 AVPlayer seek 到同一時間。這在
    /// `.ready` 之前做，讓播放器第一次可見時就已站在正確句子附近。
    func bootstrapInitialPlaybackPosition(_ time: TimeInterval?) {
        defer { initialPositionResolved = true }
        guard let time, time > 0 else { return }
        syncPlaybackPosition(time, pinLead: true)
        playbackAnchor = PodcastPlaybackClock.makeAnchor(
            mediaTime: time, now: nowRef(), rate: 0
        )
        audioEngine.seek(to: time, autoResume: false)
    }

    func setLoading() {
        state = .loading
    }

    func reportError(_ message: String) {
        state = .error(message)
    }

#if DEBUG
    /// Catalog-only: drive the VM into a deterministic, AVPlayer-free `.ready`
    /// state so the offline Playbook catalog renders the *real* player chrome
    /// (transcript + scrubber + transport) without spinning up audio or hitting
    /// the network. `syncPlaybackPosition` aligns the subtitle render state /
    /// current sentence to `currentTime`, so the captured frame shows a live,
    /// mid-episode player instead of a cold one. Never called outside DEBUG.
    func catalogReadyPreview(duration: TimeInterval, currentTime: TimeInterval, subtitleSRT: String?) {
        self.duration = duration
        if let srt = subtitleSRT {
            applySubtitle(content: srt)
        }
        self.currentTime = currentTime
        syncPlaybackPosition(currentTime, pinLead: true)
        playbackAnchor = PodcastPlaybackClock.makeAnchor(mediaTime: currentTime, now: nowRef(), rate: 0)
        initialPositionResolved = true
        state = .ready
    }
#endif

    // MARK: - Playback Controls

    func play() {
        audioEngine.play()
        state = .playing
        playbackAnchor = PodcastPlaybackClock.makeAnchor(
            mediaTime: currentTime, now: nowRef(), rate: Double(playbackRate)
        )
        PerfLog.audio.mark(
            "podcast.player.play.started",
            "time=\(Self.debugClock(currentTime)) duration=\(Self.debugClock(duration)) rate=\(playbackRate)"
        )
    }

    func pause() {
        audioEngine.pause()
        state = .paused
        playbackAnchor = PodcastPlaybackClock.makeAnchor(
            mediaTime: currentTime, now: nowRef(), rate: 0
        )
        PerfLog.audio.mark(
            "podcast.player.pause",
            "time=\(Self.debugClock(currentTime)) duration=\(Self.debugClock(duration))"
        )
    }

    /// Mid-session teardown — releases the current player/item so a new load
    /// can take over without a session-deactivation pulse. Use on retry / swap.
    func stop() {
        audioEngine.stop()
        state = .idle
    }

    /// Terminal teardown — use on view dismiss to also release the audio
    /// session + lock-screen metadata so other apps regain focus.
    func shutdown() {
        audioEngine.shutdown()
        sleepTimerSource?.cancel()
        sleepTimerSource = nil
        sleepTimerMode = .off
        sleepDeadline = nil
        state = .idle
    }

    func togglePlayPause() {
        if state == .playing { pause() } else { play() }
    }

    func seek(to time: TimeInterval) {
        let shouldResume = state == .playing
        audioEngine.seek(to: time, autoResume: shouldResume)
        // isSeek: pin the follow-scroll lead to the CURRENT sentence so a transcript
        // tap lands on the tapped bubble, not its 0.5 s-ahead successor (★B1).
        handleTimeUpdate(time, isSeek: true)
        // Hold the playhead still during the seek gap (rate 0): AVPlayer hasn't
        // actually reached `time` yet, so extrapolating forward would front-run.
        // The engine's seek-completion tick re-anchors with the real rate via
        // handleTimeUpdate once playback genuinely resumes.
        playbackAnchor = PodcastPlaybackClock.makeAnchor(mediaTime: time, now: nowRef(), rate: 0)
        PerfLog.audio.mark(
            "podcast.player.seek",
            "target=\(Self.debugClock(time)) autoResume=\(shouldResume)"
        )
    }

    func skip(seconds: Double) {
        let target = max(0, min(duration, currentTime + seconds))
        seek(to: target)
    }

    func cycleRate() {
        let next = PodcastAudioEngine.nextRate(after: playbackRate)
        playbackRate = next
        audioEngine.setRate(next)
        // Re-anchor at the new slope without a position jump (order pinned in the
        // pure helper). Rate is 0 while paused so the playhead stays put.
        let effective = state == .playing ? Double(next) : 0
        playbackAnchor = PodcastPlaybackClock.anchorAfterRateChange(
            old: playbackAnchor, now: nowRef(), newRate: effective, duration: duration
        )
        PerfLog.audio.mark(
            "podcast.player.rate.changed",
            "rate=\(next) effective=\(effective) time=\(Self.debugClock(currentTime))"
        )
    }

    // MARK: - Sleep Timer

    /// Drives the sleep timer using a wall-clock DispatchSourceTimer instead
    /// of `Task.sleep` — the latter freezes when iOS suspends the app during
    /// a user-initiated pause (no audio output → audio session goes idle).
    /// DISPATCH_TIMER_STRICT-style behavior means a missed deadline fires on
    /// foreground resume, which is the desired "auto-paused on schedule" UX.
    func setSleepTimer(_ mode: SleepTimerMode) {
        sleepTimerSource?.cancel()
        sleepTimerSource = nil
        sleepDeadline = nil
        sleepTimerMode = mode
        switch mode {
        case .off, .endOfEpisode:
            return
        case .minutes(let n):
            let seconds = max(1, n) * 60
            sleepDeadline = Date().addingTimeInterval(TimeInterval(seconds))
            let source = DispatchSource.makeTimerSource(queue: .main)
            source.schedule(deadline: .now() + .seconds(seconds))
            source.setEventHandler { [weak self] in
                MainActor.assumeIsolated {
                    self?.fireSleepTimer()
                }
            }
            sleepTimerSource = source
            source.resume()
        }
    }

    private func fireSleepTimer() {
        pause()
        sleepTimerMode = .off
        sleepDeadline = nil
        sleepTimerSource?.cancel()
        sleepTimerSource = nil
        sleepTimerFiredTick &+= 1
    }

    private static func debugClock(_ value: TimeInterval) -> String {
        guard value.isFinite, !value.isNaN else { return "nan" }
        return String(format: "%.2f", value)
    }

    // MARK: - Word Tap

    func handleWordTap(word: String, context: String) {
        activeWordSelection = (word, context)
        activePhraseSelection = nil
        activeExplainSelection = nil
        wordTapTick &+= 1
    }

    func handlePhraseTap(phrase: String, context: String) {
        activePhraseSelection = (phrase, context)
        activeWordSelection = nil
        activeExplainSelection = nil
        phraseTapTick &+= 1
    }

    func handleExplainTap(text: String, context: String) {
        activeExplainSelection = (text, context)
        activeWordSelection = nil
        activePhraseSelection = nil
        explainTapTick &+= 1
    }

    func dismissWordSelection() {
        activeWordSelection = nil
        activePhraseSelection = nil
        activeExplainSelection = nil
    }

    // MARK: - Computed

    var visibleSentences: [PodcastSentence] {
        subtitleEngine.sentences
    }

    var rateDisplayText: String {
        String(format: "×%.2g", playbackRate)
    }

    // MARK: - Private

    /// Seconds the follow-scroll target leads the spoken playhead so the next bubble
    /// reaches viewport center just before it starts. Adjustable in one place.
    /// 0.8s: a touch ahead so the upcoming subtitle visibly precedes the audio,
    /// without overshooting (too large slides the next bubble in while the current
    /// one is still being spoken). Highlight/underline stay keyed on the precise
    /// `currentSentence` — only the scroll leads.
    static let scrollLeadSec: TimeInterval = 0.8

    private func handleTimeUpdate(_ time: TimeInterval, isSeek: Bool = false) {
        syncPlaybackPosition(time, pinLead: isSeek)

        // Re-anchor the continuous playhead on every real tick (~66 ms) so the
        // View-side extrapolation never drifts beyond one tick. Rate is 0 unless
        // actively playing (paused / .ready / seeking hold the playhead still).
        playbackAnchor = PodcastPlaybackClock.makeAnchor(
            mediaTime: time, now: nowRef(), rate: state == .playing ? Double(playbackRate) : 0
        )
    }

    /// Reference-clock now, shared basis with the consuming `TimelineView`'s
    /// `context.date.timeIntervalSinceReferenceDate`.
    private func nowRef() -> TimeInterval { Date().timeIntervalSinceReferenceDate }

    private func syncPlaybackPosition(_ time: TimeInterval, pinLead: Bool) {
        currentTime = time

        let sentence = subtitleEngine.currentSentence(at: time)
        if sentence?.id != currentSentence?.id {
            currentSentence = sentence
            if let sentence {
                renderState = SubtitleRenderState(from: sentence, hostNames: hostNames)
            } else {
                renderState = nil
            }
        }

        let leadId = PodcastSubtitleEngine.scrollLeadSentenceId(
            in: subtitleEngine.sentences, at: time, isSeek: pinLead, leadSec: Self.scrollLeadSec
        )
        if leadId != scrollLeadSentenceId {
            scrollLeadSentenceId = leadId
        }
    }
}
