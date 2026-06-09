#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

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

    @Test func initialScrollWaitsUntilPositionIsResolved() {
        let decision = PodcastTranscriptScrollPolicy.initialDecision(
            initialScrollPositionResolved: false,
            didApplyInitialScrollPosition: false,
            currentId: 42
        )

        #expect(decision == .none)
    }

    @Test func initialScrollDoesNotRepeatAfterApplied() {
        let decision = PodcastTranscriptScrollPolicy.initialDecision(
            initialScrollPositionResolved: true,
            didApplyInitialScrollPosition: true,
            currentId: 42
        )

        #expect(decision == .none)
    }

    @Test func initialScrollMarksAppliedWhenCurrentSentenceIsUnavailable() {
        let decision = PodcastTranscriptScrollPolicy.initialDecision(
            initialScrollPositionResolved: true,
            didApplyInitialScrollPosition: false,
            currentId: nil
        )

        #expect(decision == .markAppliedWithoutTarget)
    }

    @Test func initialScrollTargetsCurrentSentenceWhenAvailable() {
        let decision = PodcastTranscriptScrollPolicy.initialDecision(
            initialScrollPositionResolved: true,
            didApplyInitialScrollPosition: false,
            currentId: 7
        )

        #expect(decision == .scrollTo(7))
    }

    @Test func followScrollWaitsUntilInitialScrollApplied() {
        let target = PodcastTranscriptScrollPolicy.followTarget(
            isFollowing: true,
            didApplyInitialScrollPosition: false,
            targetId: 7
        )

        #expect(target == nil)
    }

    @Test func followScrollWaitsWhenFollowIsDisabled() {
        let target = PodcastTranscriptScrollPolicy.followTarget(
            isFollowing: false,
            didApplyInitialScrollPosition: true,
            targetId: 7
        )

        #expect(target == nil)
    }

    @Test func followScrollTargetsLeadSentenceWhenReady() {
        let target = PodcastTranscriptScrollPolicy.followTarget(
            isFollowing: true,
            didApplyInitialScrollPosition: true,
            targetId: 7
        )

        #expect(target == 7)
    }

    @Test func manualDragOnlyDisengagesActiveFollowMode() {
        #expect(PodcastTranscriptScrollPolicy.shouldDisengageFollowOnManualDrag(isFollowing: true))
        #expect(PodcastTranscriptScrollPolicy.shouldDisengageFollowOnManualDrag(isFollowing: false) == false)
    }

    private func cue(_ word: String) -> PodcastSubtitleCue {
        PodcastSubtitleCue(id: 0, startTime: 0, endTime: 1, speaker: "A", word: word)
    }
}
#endif
