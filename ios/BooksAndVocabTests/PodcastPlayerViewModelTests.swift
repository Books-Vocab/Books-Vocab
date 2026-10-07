import Foundation
import Testing
@testable import BooksAndVocab

@MainActor
struct PodcastPlayerViewModelTests {
    @Test
    func injectedEnginesDrivePlaybackLifecycle() {
        let audio = FakeAudioEngine()
        let subtitles = FakeSubtitleEngine()
        let viewModel = PodcastPlayerViewModel(
            hostNames: ["Maya"],
            audioEngine: audio,
            subtitleEngine: subtitles
        )

        #expect(viewModel.state == .idle)
        viewModel.loadEpisode(
            audioURL: URL(string: "https://example.com/episode.mp3")!,
            subtitleContent: nil,
            title: "Episode"
        )
        #expect(viewModel.state == .loading)
        #expect(audio.loadCount == 1)

        audio.emitReady()
        #expect(viewModel.state == .ready)

        viewModel.play()
        #expect(viewModel.state == .playing)
        audio.emitTimeUpdate(12.5)
        #expect(viewModel.currentTime == 12.5)

        audio.emitSystemPause()
        #expect(viewModel.state == .paused)
        audio.emitSystemResume()
        #expect(viewModel.state == .playing)

        audio.emitPlaybackFinished()
        #expect(viewModel.state == .ready)
        #expect(viewModel.episodeFinishedTick == 1)
    }

    // #2103: lock-screen / Control Center play must reach vm.state, otherwise
    // the progress ticker (gated on `state == .playing`) never saves.
    @Test
    func remotePlayAfterInAppPauseMovesViewModelToPlaying() {
        let (audio, viewModel) = makeReadyViewModel()
        viewModel.play()
        viewModel.pause()

        audio.emitRemotePlay()

        #expect(viewModel.state == .playing)
        #expect(audio.playCount == 2)
        #expect(audio.isPlaying)
        audio.emitTimeUpdate(30)
        #expect(viewModel.currentTime == 30)
        #expect(viewModel.playbackAnchor.rate == 1)
    }

    @Test
    func remotePauseWhilePlayingMovesViewModelToPaused() {
        let (audio, viewModel) = makeReadyViewModel()
        viewModel.play()

        audio.emitRemotePause()

        #expect(viewModel.state == .paused)
        #expect(audio.pauseCount == 1)
        #expect(!audio.isPlaying)
    }

    // #2103: `.shouldResume` only means "you may resume"; a user who paused
    // before the interruption must stay paused.
    @Test
    func interruptionShouldResumeAfterUserPauseDoesNotPlay() {
        let (audio, viewModel) = makeReadyViewModel()
        viewModel.play()
        viewModel.pause()

        audio.emitSystemPause()
        audio.emitSystemResume()

        #expect(audio.playCount == 1)
        #expect(viewModel.state == .paused)
    }

    @Test
    func interruptionShouldResumeWhilePlayingResumesThroughTheEngine() {
        let (audio, viewModel) = makeReadyViewModel()
        viewModel.play()

        audio.emitSystemPause()
        #expect(viewModel.state == .paused)
        audio.emitSystemResume()

        #expect(audio.playCount == 2)
        #expect(audio.isPlaying)
        #expect(viewModel.state == .playing)
    }

    @Test
    func userPauseDuringInterruptionCancelsTheResume() {
        let (audio, viewModel) = makeReadyViewModel()
        viewModel.play()

        audio.emitSystemPause()
        viewModel.pause()
        audio.emitSystemResume()

        #expect(audio.playCount == 1)
        #expect(viewModel.state == .paused)
    }

    @Test
    func injectedAudioFailureBecomesPlayerError() {
        let audio = FakeAudioEngine()
        let viewModel = PodcastPlayerViewModel(
            hostNames: [],
            audioEngine: audio,
            subtitleEngine: FakeSubtitleEngine()
        )

        viewModel.loadEpisode(
            audioURL: URL(string: "https://example.com/episode.mp3")!,
            subtitleContent: nil
        )
        audio.emitLoadFailure("fixture failure")

        #expect(viewModel.state == .error("fixture failure"))
    }

    @Test
    func skipForwardBeforeDurationLoadsPreservesTheRequestedTarget() {
        let audio = FakeAudioEngine()
        let viewModel = PodcastPlayerViewModel(
            hostNames: [],
            audioEngine: audio,
            subtitleEngine: FakeSubtitleEngine()
        )

        viewModel.loadEpisode(
            audioURL: URL(string: "https://example.com/episode.mp3")!,
            subtitleContent: nil
        )
        viewModel.skip(seconds: 15)

        #expect(viewModel.duration == 0)
        #expect(audio.currentTime == 15)
    }

    @Test
    func injectedSubtitleEngineDrivesVisibleSentences() {
        let audio = FakeAudioEngine()
        let subtitles = FakeSubtitleEngine(sentences: [
            PodcastSentence(
                id: 0,
                speaker: "Maya",
                text: "hello",
                startTime: 0,
                endTime: 2,
                words: []
            )
        ])
        let viewModel = PodcastPlayerViewModel(
            hostNames: ["Maya"],
            audioEngine: audio,
            subtitleEngine: subtitles
        )

        viewModel.loadEpisode(
            audioURL: URL(string: "https://example.com/episode.mp3")!,
            subtitleContent: "fixture srt"
        )
        audio.emitTimeUpdate(1)

        #expect(subtitles.loadCount == 1)
        #expect(viewModel.subtitleState == .loaded)
        #expect(viewModel.visibleSentences == subtitles.sentences)
        #expect(viewModel.currentSentence?.id == 0)
    }

    private func makeReadyViewModel() -> (FakeAudioEngine, PodcastPlayerViewModel) {
        let audio = FakeAudioEngine()
        let viewModel = PodcastPlayerViewModel(
            hostNames: [],
            audioEngine: audio,
            subtitleEngine: FakeSubtitleEngine()
        )
        viewModel.loadEpisode(
            audioURL: URL(string: "https://example.com/episode.mp3")!,
            subtitleContent: nil
        )
        audio.emitReady()
        return (audio, viewModel)
    }
}

@MainActor
private final class FakeAudioEngine: PodcastAudioPlaying {
    var playbackRate: Float = 1
    var duration: TimeInterval = 0
    var currentTime: TimeInterval = 0
    var isPlaying = false
    var loadCount = 0
    private(set) var playCount = 0
    private(set) var pauseCount = 0

    var onTimeUpdate: ((TimeInterval) -> Void)?
    var onPlaybackFinished: (() -> Void)?
    var onDurationLoaded: ((TimeInterval) -> Void)?
    var onReadyToPlay: (() -> Void)?
    var onLoadFailed: ((String) -> Void)?
    var onBufferedEndChanged: ((TimeInterval) -> Void)?
    var onSystemPause: (() -> Void)?
    var onSystemResume: (() -> Void)?
    var onRemotePlay: (() -> Void)?
    var onRemotePause: (() -> Void)?

    func loadAudio(
        url: URL,
        httpHeaders: [String: String],
        prefetchedDuration: TimeInterval?
    ) {
        loadCount += 1
    }

    func configureNowPlaying(title: String, artist: String) {}

    func play() {
        playCount += 1
        isPlaying = true
    }
    func pause() {
        pauseCount += 1
        isPlaying = false
    }
    func stop() { isPlaying = false }
    func shutdown() { isPlaying = false }
    func seek(to time: TimeInterval, autoResume: Bool) {
        currentTime = time
        isPlaying = autoResume
    }
    func setRate(_ rate: Float) { playbackRate = rate }

    func emitReady() { onReadyToPlay?() }
    func emitLoadFailure(_ message: String) { onLoadFailed?(message) }
    func emitPlaybackFinished() { onPlaybackFinished?() }
    /// Real engine: interruption `.began` / route loss pauses the player, then
    /// reports it. Mirror that so the fake's `isPlaying` matches reality.
    func emitSystemPause() {
        isPlaying = false
        onSystemPause?()
    }
    func emitSystemResume() { onSystemResume?() }
    /// Lock-screen / Control Center command routed to the owner (engine falls
    /// back to its own play()/pause() only when no owner handler is set).
    func emitRemotePlay() { if let onRemotePlay { onRemotePlay() } else { play() } }
    func emitRemotePause() { if let onRemotePause { onRemotePause() } else { pause() } }
    func emitTimeUpdate(_ time: TimeInterval) {
        currentTime = time
        onTimeUpdate?(time)
    }
}

private final class FakeSubtitleEngine: PodcastSubtitling {
    private(set) var loadCount = 0
    private(set) var sentences: [PodcastSentence]

    init(sentences: [PodcastSentence] = []) {
        self.sentences = sentences
    }

    func load(srtContent: String) {
        loadCount += 1
    }

    func currentSentence(at time: TimeInterval) -> PodcastSentence? {
        sentences.first { $0.startTime <= time && time < $0.endTime }
    }
}
