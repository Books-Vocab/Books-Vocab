import Foundation
import Testing
@testable import BooksAndVocab

/// Unit tests for `PodcastAudioEngine`.
///
/// The engine is heavily coupled to `AVPlayer` / `AVAudioSession` / `MPRemoteCommandCenter`,
/// which cannot be driven deterministically inside a unit-test process (no real audio
/// route, no media item, async asset metadata loads). These tests therefore pin the
/// **pure-state seams** that need no live player:
///
///  - `rateSteps` / `nextRate(after:)` — the speed-cycle state machine.
///  - `sourceToken(from:)` — the PII-free breadcrumb token derivation.
///  - `setRate` clamp range + the no-player getters (`currentTime`, `isPlaying`,
///    `duration`, `playbackRate`) which form the engine's well-defined "cold" contract.
///  - `stop()` / `shutdown()` on a freshly-constructed engine — must be no-op-safe so
///    a VM can tear down before any `loadAudio`.
///
/// Trade-off: the play/pause/seek **transition** behaviour and the subtitle-highlight
/// index calculation are exercised at the `PodcastPlayerViewModel` / `SubtitleRenderState`
/// layer, not here — those need either a real `AVPlayer` (transition timing) or live
/// `PodcastSentence` cue data (highlight). The engine's seek *clamping* arithmetic is
/// re-implemented and verified in `seek_clamp_*` tests below, since the production
/// `seek(to:)` formula (`max(0, duration > 0 ? min(time, duration) : time)`) is the
/// load-bearing boundary logic and is otherwise unreachable without a player.
struct PodcastAudioEngineTests {

    // MARK: - rateSteps invariants

    @Test func rateSteps_areSortedAscendingUnique() {
        let steps = PodcastAudioEngine.rateSteps
        #expect(steps == [0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
        #expect(steps == steps.sorted(), "rate ladder must be ascending")
        #expect(Set(steps).count == steps.count, "no duplicate rate steps")
    }

    @Test func rateSteps_allWithinSupportedClampRange() {
        // Every advertised step must survive `setRate`'s 0.5...2.0 clamp unchanged.
        for step in PodcastAudioEngine.rateSteps {
            #expect(step >= 0.5 && step <= 2.0)
        }
    }

    // MARK: - nextRate cycle

    @Test func nextRate_advancesOneStep() {
        #expect(PodcastAudioEngine.nextRate(after: 0.5) == 0.75)
        #expect(PodcastAudioEngine.nextRate(after: 0.75) == 1.0)
        #expect(PodcastAudioEngine.nextRate(after: 1.0) == 1.25)
        #expect(PodcastAudioEngine.nextRate(after: 1.25) == 1.5)
        #expect(PodcastAudioEngine.nextRate(after: 1.5) == 2.0)
    }

    @Test func nextRate_wrapsFromMaxToMin() {
        // Top of the ladder cycles back to the slowest speed.
        #expect(PodcastAudioEngine.nextRate(after: 2.0) == 0.5)
    }

    @Test func nextRate_fullCycleReturnsToStart() {
        var rate: Float = 1.0
        let visited = (0..<PodcastAudioEngine.rateSteps.count).map { _ -> Float in
            rate = PodcastAudioEngine.nextRate(after: rate)
            return rate
        }
        #expect(rate == 1.0, "advancing exactly rateSteps.count times returns to the origin")
        #expect(Set(visited) == Set(PodcastAudioEngine.rateSteps),
                "a full cycle visits every rate exactly once")
    }

    @Test func nextRate_unknownRateFallsBackToOne() {
        // An off-ladder rate (e.g. legacy persisted value) must not crash; it
        // resets to the neutral 1.0× rather than guessing a neighbour.
        #expect(PodcastAudioEngine.nextRate(after: 1.1) == 1.0)
        #expect(PodcastAudioEngine.nextRate(after: 3.0) == 1.0)
        #expect(PodcastAudioEngine.nextRate(after: 0.0) == 1.0)
    }

    @Test func nextRate_toleratesFloatingPointDrift() {
        // The match uses `abs(diff) < 0.01`, so a rate that is *almost* a step
        // (typical after Float round-tripping through JSON / UserDefaults) still
        // advances correctly instead of falling back to 1.0.
        #expect(PodcastAudioEngine.nextRate(after: 0.7501) == 1.0)
        #expect(PodcastAudioEngine.nextRate(after: 1.4999) == 2.0)
    }

    // MARK: - sourceToken derivation

    @Test func sourceToken_extractsSeriesAndEpisodeFromPodcastMediaURL() {
        let url = URL(string: "https://wordnexus.lol/api/podcast-media/flow_950f1a7d/ep_03/audio.mp3")!
        #expect(PodcastAudioEngine.sourceToken(from: url) == "flow_950f1a7d/ep_03")
    }

    @Test func sourceToken_dropsQueryString() {
        // Breadcrumb must stay PII-free — any query (signed URL token, etc.) is dropped.
        let url = URL(string: "https://wordnexus.lol/api/podcast-media/series_x/ep_01/a.mp3?token=secret")!
        #expect(PodcastAudioEngine.sourceToken(from: url) == "series_x/ep_01")
    }

    @Test func sourceToken_fallsBackToLastPathComponentForUnknownShape() {
        // A URL without the `podcast-media` marker falls back to the filename
        // (extension stripped) so the breadcrumb is still meaningful.
        let url = URL(string: "https://example.com/files/episode_42.mp3")!
        #expect(PodcastAudioEngine.sourceToken(from: url) == "episode_42")
    }

    @Test func sourceToken_fallbackOnPodcastMediaURLTooShort() {
        // `podcast-media` present but not enough trailing components for
        // `<series>/<episode>` → fall back rather than index out of bounds.
        let url = URL(string: "https://wordnexus.lol/api/podcast-media/only_series")!
        #expect(PodcastAudioEngine.sourceToken(from: url) == "only_series")
    }

    @Test func sourceToken_handlesFileURL() {
        let url = URL(fileURLWithPath: "/tmp/local_episode.mp3")
        #expect(PodcastAudioEngine.sourceToken(from: url) == "local_episode")
    }

    // MARK: - Cold engine contract (no loadAudio called)

    @Test func freshEngine_hasNeutralDefaults() {
        let engine = PodcastAudioEngine()
        #expect(engine.playbackRate == 1.0, "default rate is 1.0×")
        #expect(engine.duration == 0, "no asset → duration 0")
        #expect(engine.currentTime == 0, "no player → currentTime 0")
        #expect(engine.isPlaying == false, "no player → not playing")
    }

    @Test func freshEngine_playPauseAreNoOpSafe() {
        // A VM may call play()/pause() before any episode is loaded (e.g. a
        // remote-command race). These must not crash and must not flip state.
        let engine = PodcastAudioEngine()
        engine.play()
        engine.pause()
        #expect(engine.isPlaying == false)
        #expect(engine.currentTime == 0)
    }

    @Test func freshEngine_seekIsNoOpSafe() {
        // seek() guards on `player != nil`; calling it cold must be harmless.
        let engine = PodcastAudioEngine()
        engine.seek(to: 30, autoResume: true)
        #expect(engine.currentTime == 0)
        #expect(engine.isPlaying == false)
    }

    @Test func freshEngine_stopAndShutdownAreNoOpSafe() {
        // Terminal teardown before any load must not crash (view dismissed
        // before `.task` ran loadEpisode).
        let engine = PodcastAudioEngine()
        engine.stop()
        engine.shutdown()
        #expect(engine.duration == 0)
        #expect(engine.isPlaying == false)
    }

    // MARK: - setRate clamping

    @Test func setRate_withinRangeIsAppliedVerbatim() {
        let engine = PodcastAudioEngine()
        for rate in PodcastAudioEngine.rateSteps {
            engine.setRate(rate)
            #expect(engine.playbackRate == rate)
        }
    }

    @Test func setRate_clampsBelowMinimum() {
        let engine = PodcastAudioEngine()
        engine.setRate(0.1)
        #expect(engine.playbackRate == 0.5, "rate floor is 0.5×")
        engine.setRate(-1.0)
        #expect(engine.playbackRate == 0.5, "negative rate clamps to floor, never reverses playback")
    }

    @Test func setRate_clampsAboveMaximum() {
        let engine = PodcastAudioEngine()
        engine.setRate(5.0)
        #expect(engine.playbackRate == 2.0, "rate ceiling is 2.0×")
    }

    @Test func setRate_persistsAcrossCycleHelper() {
        // `cycleRate` in the VM relies on the engine retaining the rate it set
        // so the next `nextRate(after:)` advances from the real current value.
        let engine = PodcastAudioEngine()
        engine.setRate(1.5)
        let next = PodcastAudioEngine.nextRate(after: engine.playbackRate)
        engine.setRate(next)
        #expect(engine.playbackRate == 2.0)
    }

    // MARK: - seek clamp boundary arithmetic

    /// Mirror of the production clamp in `PodcastAudioEngine.seek(to:autoResume:)`:
    /// `max(0, duration > 0 ? min(time, duration) : time)`.
    /// Re-implemented here because the real method is unreachable without a live
    /// `AVPlayer`; the boundary behaviour is load-bearing (end-of-episode scrubber
    /// alignment, negative-seek defence) so it is pinned explicitly.
    private func clampSeek(_ time: TimeInterval, duration: TimeInterval) -> TimeInterval {
        max(0, duration > 0 ? min(time, duration) : time)
    }

    @Test func seekClamp_negativeTimeClampsToZero() {
        #expect(clampSeek(-10, duration: 120) == 0, "seeking before the start pins to 0")
    }

    @Test func seekClamp_beyondDurationClampsToDuration() {
        #expect(clampSeek(999, duration: 120) == 120, "seeking past the end pins to file end")
    }

    @Test func seekClamp_withinRangeIsUnchanged() {
        #expect(clampSeek(45, duration: 120) == 45)
        #expect(clampSeek(0, duration: 120) == 0)
        #expect(clampSeek(120, duration: 120) == 120)
    }

    @Test func seekClamp_unknownDurationKeepsNonNegativeTime() {
        // duration == 0 means metadata hasn't loaded yet: a forward seek is kept
        // as-is (no ceiling), but a negative seek is still floored at 0.
        #expect(clampSeek(75, duration: 0) == 75)
        #expect(clampSeek(-5, duration: 0) == 0)
    }
}
