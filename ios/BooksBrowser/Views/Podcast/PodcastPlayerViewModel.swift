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

/// Lifecycle of the subtitle (SRT) load, tracked separately from audio.
///
/// A failed subtitle fetch used to be swallowed by `try?` — audio kept
/// playing while subtitles were permanently missing with no prompt. This
/// state lets the player surface an inline "字幕載入失敗 ⟳" retry without
/// interrupting playback. `.idle` covers both "not started" and "episode
/// ships no subtitle URL" — neither warrants a failure prompt.
enum PodcastSubtitleLoadState: Equatable {
    case idle
    case loading
    case loaded
    case failed
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
    private(set) var currentCue: PodcastSubtitleCue?
    private(set) var renderState: SubtitleRenderState?
    private(set) var highlightedWordIndex: Int = -1
    private(set) var playbackRate: Float = 1.0
    /// Subtitle load lifecycle — drives the inline retry UI. Independent of
    /// `state` so a subtitle failure never blocks or interrupts audio.
    private(set) var subtitleState: PodcastSubtitleLoadState = .idle
    let hostNames: [String]

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
        prefetchedDurationSec: TimeInterval = 0
    ) {
        state = .loading
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
        // state → .ready (via onReadyToPlay) or .error (via onLoadFailed) arrives async.
    }

    // MARK: - Subtitle load lifecycle

    /// Marks the subtitle fetch as in-flight. Use before kicking off the
    /// network load and again on retry.
    func setSubtitleLoading() {
        subtitleState = .loading
    }

    /// Parses fetched SRT content into sentences and marks the load loaded.
    func applySubtitle(content: String) {
        subtitleEngine.load(srtContent: content)
        subtitleState = .loaded
    }

    /// Marks the subtitle fetch as failed — drives the inline retry UI.
    func markSubtitleFailed() {
        subtitleState = .failed
    }

    /// The episode genuinely ships no subtitle URL. Stays `.idle` so no
    /// spurious failure prompt appears.
    func markSubtitleUnavailable() {
        subtitleState = .idle
    }

    func setLoading() {
        state = .loading
    }

    func reportError(_ message: String) {
        state = .error(message)
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
        state = .idle
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

    private func handleTimeUpdate(_ time: TimeInterval) {
        currentTime = time
        let cue = subtitleEngine.currentCue(at: time)
        currentCue = cue

        // Low-frequency path: only rebuild renderState when sentence changes
        let sentence = subtitleEngine.currentSentence(at: time)
        if sentence?.id != currentSentence?.id {
            currentSentence = sentence
            if let sentence {
                renderState = SubtitleRenderState(from: sentence, hostNames: hostNames)
            } else {
                renderState = nil
            }
        }

        // High-frequency path: highlight = index of current cue within sentence.words.
        // With compact SRT, sentence.words is 1:1 with word cues, so we find the cue
        // position directly (no fuzzy text match needed).
        if let cue, let sentence = currentSentence,
           let idx = sentence.words.firstIndex(where: { $0.id == cue.id }) {
            highlightedWordIndex = idx
        } else {
            highlightedWordIndex = -1
        }
    }
}
