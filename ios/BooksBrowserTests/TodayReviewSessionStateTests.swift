import Testing
@testable import BooksBrowser

struct TodayReviewSessionStateTests {

    @Test func advancingAndRetractingRevealOnlyMovesBetweenFrontAndBack() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta"])

        #expect(state.revealStage == .front)
        #expect(state.advanceReveal())
        #expect(state.revealStage == .back)

        #expect(state.advanceReveal() == false)
        #expect(state.revealStage == .back)

        #expect(state.retractReveal())
        #expect(state.revealStage == .front)

        #expect(state.retractReveal() == false)
        #expect(state.revealStage == .front)
    }

    @Test func navigationResetsRevealAndMovesWithinQueueBounds() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta", "gamma"])

        #expect(state.goPrevious() == false)
        #expect(state.currentIndex == 0)

        #expect(state.advanceReveal())
        #expect(state.revealStage == .back)

        #expect(state.goNext())
        #expect(state.currentIndex == 1)
        #expect(state.revealStage == .front)

        #expect(state.goPrevious())
        #expect(state.currentIndex == 0)
        #expect(state.revealStage == .front)
    }

    @Test func advanceAfterSubmissionMovesPastQueueAndReportsCompletion() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta"])

        #expect(state.advanceAfterSubmission() == false)
        #expect(state.currentIndex == 1)
        #expect(state.currentEntry == "beta")
        #expect(state.revealStage == .front)

        #expect(state.advanceAfterSubmission())
        #expect(state.currentIndex == 2)
        #expect(state.currentEntry == nil)
        #expect(state.isComplete)
    }

    @Test func shufflePreservesPrefixMembershipAndResetsReveal() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta", "gamma", "delta"])
        state.currentIndex = 1
        _ = state.advanceReveal()

        var rng = FixedIndexRNG(indices: [1, 1])
        #expect(state.shuffleRemaining(using: &rng))

        #expect(state.queue[0] == "alpha")
        #expect(state.currentIndex == 1)
        #expect(Set(state.queue[1...]) == Set(["beta", "gamma", "delta"]))
        #expect(state.revealStage == .front)
    }
}

private struct FixedIndexRNG: RandomNumberGenerator {
    private var indices: [UInt64]
    private var cursor = 0

    init(indices: [UInt64]) {
        self.indices = indices
    }

    mutating func next() -> UInt64 {
        guard cursor < indices.count else { return 0 }
        defer { cursor += 1 }
        return indices[cursor]
    }
}
