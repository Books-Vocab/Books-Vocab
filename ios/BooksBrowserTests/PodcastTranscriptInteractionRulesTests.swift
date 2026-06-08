#if os(iOS)
import Foundation
import Testing
@testable import BooksBrowser

@Suite("PodcastTranscriptInteractionRules")
struct PodcastTranscriptInteractionRulesTests {
    @Test func followControlHiddenDuringSelectionOnAllPlatforms() {
        #expect(PodcastFollowControlVisibility.shouldShow(
            isFollowing: true,
            hasActiveSelection: true,
            isCatalyst: true
        ) == false)
        #expect(PodcastFollowControlVisibility.shouldShow(
            isFollowing: false,
            hasActiveSelection: true,
            isCatalyst: false
        ) == false)
    }

    @Test func followControlIsAlwaysAvailableOnCatalystWhenNotSelecting() {
        #expect(PodcastFollowControlVisibility.shouldShow(
            isFollowing: true,
            hasActiveSelection: false,
            isCatalyst: true
        ) == true)
        #expect(PodcastFollowControlVisibility.shouldShow(
            isFollowing: false,
            hasActiveSelection: false,
            isCatalyst: true
        ) == true)
    }

    @Test func followControlShowsOnTouchPlatformsOnlyAfterManualBrowse() {
        #expect(PodcastFollowControlVisibility.shouldShow(
            isFollowing: true,
            hasActiveSelection: false,
            isCatalyst: false
        ) == false)
        #expect(PodcastFollowControlVisibility.shouldShow(
            isFollowing: false,
            hasActiveSelection: false,
            isCatalyst: false
        ) == true)
    }

    @Test func selectionRangeFindsRepeatedWordByIndex() {
        let words = [
            cue("well"),
            cue("well"),
            cue("said")
        ]
        let range = PodcastSentenceSelectionRange.range(
            in: "well well said",
            words: words,
            wordIndex: 1
        )

        #expect(range == NSRange(location: 5, length: 4))
    }

    @Test func selectionRangeReturnsNilWhenWordMissing() {
        let range = PodcastSentenceSelectionRange.range(
            in: "hello world",
            words: [cue("missing")],
            wordIndex: 0
        )

        #expect(range == nil)
    }

    private func cue(_ word: String) -> PodcastSubtitleCue {
        PodcastSubtitleCue(id: 0, startTime: 0, endTime: 1, speaker: "A", word: word)
    }
}
#endif
