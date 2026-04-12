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
    private(set) var playbackRate: Float = 1.0
    private(set) var displayMode: PodcastSubtitleDisplayMode = .wordLevel
    let hostNames: [String]

    // Low-frequency: only changes when sentence switches (~0.2 Hz)
    private(set) var renderState: SubtitleRenderState?
    // High-frequency: changes at ~30fps, just an Int — does NOT trigger sentence re-render
    private(set) var highlightedWordIndex: Int = -1

    // Keep for backward compat / sentence-level view
    private(set) var currentSentence: PodcastSentence?
    private(set) var currentCue: PodcastSubtitleCue?

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
            rebuildRenderState(for: sentence)
        }

        // High-frequency path: update highlight index from cue
        if let word = cue?.highlightedWord, let rs = renderState {
            let normalized = word.lowercased().trimmingCharacters(in: .punctuationCharacters)
            highlightedWordIndex = rs.highlightIndex(for: normalized)
        } else {
            highlightedWordIndex = -1
        }
    }

    private func rebuildRenderState(for sentence: PodcastSentence?) {
        guard let sentence else {
            renderState = nil
            return
        }
        renderState = SubtitleRenderState(from: sentence, hostNames: hostNames)
    }
}
