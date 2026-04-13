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
    private(set) var renderState: SubtitleRenderState?
    private(set) var highlightedWordIndex: Int = -1
    private(set) var playbackRate: Float = 1.0
    private(set) var displayMode: PodcastSubtitleDisplayMode = .wordLevel
    let hostNames: [String]

    // Translation — set by the player view
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
        audioEngine.onDurationLoaded = { [weak self] d in
            MainActor.assumeIsolated {
                self?.duration = d
            }
        }
        audioEngine.onReadyToPlay = { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                if self.state == .loading { self.state = .ready }
            }
        }
    }

    // MARK: - Loading

    func loadEpisode(audioURL: URL, subtitleContent: String?) {
        state = .loading
        duration = 0
        do {
            try audioEngine.loadAudio(url: audioURL)
            if let srt = subtitleContent {
                subtitleEngine.load(srtContent: srt)
            }
            // With AVPlayer streaming, duration + readiness arrive asynchronously.
            // state transitions to .ready via onReadyToPlay callback.
        } catch {
            state = .error(error.localizedDescription)
        }
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

        // High-frequency path: update highlight index (just an Int, cheap)
        if let hw = cue?.highlightedWord, let rs = renderState {
            let normalized = hw.lowercased().trimmingCharacters(in: .punctuationCharacters)
            highlightedWordIndex = rs.highlightIndex(for: normalized)
        } else {
            highlightedWordIndex = -1
        }
    }
}
