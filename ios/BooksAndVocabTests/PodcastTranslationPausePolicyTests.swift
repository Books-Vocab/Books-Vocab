#if os(iOS)
import Testing
@testable import BooksAndVocab

@Suite("Podcast translation pause policy")
struct PodcastTranslationPausePolicyTests {
    @Test func openingPanelWhilePlayingPausesAndMarksAutoPaused() {
        let action = PodcastTranslationPausePolicy.action(
            autoPauseEnabled: true,
            wasPanelVisible: false,
            isPanelVisible: true,
            playerState: .playing,
            autoPausedByTranslation: false
        )

        #expect(action == .pauseAndMarkAutoPaused)
    }

    @Test func openingPanelWhileNotPlayingDoesNothing() {
        let action = PodcastTranslationPausePolicy.action(
            autoPauseEnabled: true,
            wasPanelVisible: false,
            isPanelVisible: true,
            playerState: .paused,
            autoPausedByTranslation: false
        )

        #expect(action == .none)
    }

    @Test func closingAutoPausedPanelWhilePausedResumesAndClearsFlag() {
        let action = PodcastTranslationPausePolicy.action(
            autoPauseEnabled: true,
            wasPanelVisible: true,
            isPanelVisible: false,
            playerState: .paused,
            autoPausedByTranslation: true
        )

        #expect(action == .resumeAndClearAutoPaused)
    }

    @Test func closingAutoPausedPanelWhenPlayerIsNotPausedOnlyClearsFlag() {
        let action = PodcastTranslationPausePolicy.action(
            autoPauseEnabled: true,
            wasPanelVisible: true,
            isPanelVisible: false,
            playerState: .ready,
            autoPausedByTranslation: true
        )

        #expect(action == .clearAutoPaused)
    }

    @Test func disabledAutoPauseNeverActs() {
        let action = PodcastTranslationPausePolicy.action(
            autoPauseEnabled: false,
            wasPanelVisible: false,
            isPanelVisible: true,
            playerState: .playing,
            autoPausedByTranslation: false
        )

        #expect(action == .none)
    }
}
#endif
