import Foundation
import Testing
import SwiftData
@testable import BooksAndVocab

struct TodayReviewSessionStateTests {

    @Test func advancingAndRetractingRevealOnlyMovesBetweenFrontAndBack() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta"])

        #expect(state.revealStage == .front)
        // Swift Testing's #expect captures its expression into an immutable
        // closure ($0), so mutating members must be called before the macro.
        let advancedToBack = state.advanceReveal()
        #expect(advancedToBack)
        #expect(state.revealStage == .back)

        let advanceBlockedAtBack = state.advanceReveal()
        #expect(advanceBlockedAtBack == false)
        #expect(state.revealStage == .back)

        let retractedToFront = state.retractReveal()
        #expect(retractedToFront)
        #expect(state.revealStage == .front)

        let retractBlockedAtFront = state.retractReveal()
        #expect(retractBlockedAtFront == false)
        #expect(state.revealStage == .front)
    }

    @Test func navigationResetsRevealAndMovesWithinQueueBounds() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta", "gamma"])

        let previousBlockedAtStart = state.goPrevious()
        #expect(previousBlockedAtStart == false)
        #expect(state.currentIndex == 0)

        let revealedBack = state.advanceReveal()
        #expect(revealedBack)
        #expect(state.revealStage == .back)

        let movedNext = state.goNext()
        #expect(movedNext)
        #expect(state.currentIndex == 1)
        #expect(state.revealStage == .front)

        let movedPrevious = state.goPrevious()
        #expect(movedPrevious)
        #expect(state.currentIndex == 0)
        #expect(state.revealStage == .front)
    }

    @Test func advanceAfterSubmissionMovesPastQueueAndReportsCompletion() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta"])

        let advancedWithinQueue = state.advanceAfterSubmission()
        #expect(advancedWithinQueue == false)
        #expect(state.currentIndex == 1)
        #expect(state.currentEntry == "beta")
        #expect(state.revealStage == .front)

        let advancedPastQueue = state.advanceAfterSubmission()
        #expect(advancedPastQueue)
        #expect(state.currentIndex == 2)
        #expect(state.currentEntry == nil)
        #expect(state.isComplete)
    }

    @Test func shufflePreservesPrefixMembershipAndResetsReveal() {
        var state = TodayReviewSessionState(queue: ["alpha", "beta", "gamma", "delta"])
        state.currentIndex = 1
        _ = state.advanceReveal()

        var rng = FixedIndexRNG(indices: [1, 1])
        let shuffled = state.shuffleRemaining(using: &rng)
        #expect(shuffled)

        #expect(state.queue[0] == "alpha")
        #expect(state.currentIndex == 1)
        #expect(Set(state.queue[1...]) == Set(["beta", "gamma", "delta"]))
        #expect(state.revealStage == .front)
    }

    @Test @MainActor func submittedAnswersStayBoundToCardIdentityAfterShuffle() throws {
        let userID = "today-review-shuffle-score-test"
        TodayReviewSessionSnapshotStore.clear(for: nil)
        ReviewSessionStore.clear(userID: userID)
        defer {
            TodayReviewSessionSnapshotStore.clear(for: userID)
            ReviewSessionStore.clear(userID: userID)
        }

        let container = try ModelContainer(
            for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = ModelContext(container)
        let alpha = VocabularyEntry(
            word: "alpha", translation: "A", context: "Alpha context", bookTitle: "Sample"
        )
        let beta = VocabularyEntry(
            word: "beta", translation: "B", context: "Beta context", bookTitle: "Sample"
        )
        let gamma = VocabularyEntry(
            word: "gamma", translation: "C", context: "Gamma context", bookTitle: "Sample"
        )
        for entry in [alpha, beta, gamma] {
            entry.markSynced()
            context.insert(entry)
        }
        #expect(context.safeSave())

        let state = TodayReviewState(
            entries: [alpha, beta, gamma],
            allEntries: [alpha, beta, gamma],
            currentUserID: userID
        )
        #expect(state.queue.map(\.id) == [alpha.id, beta.id, gamma.id])

        state.submit(.remembered, container: container, reviewSettings: .default)
        state.submit(.forgot, container: container, reviewSettings: .default)
        state.goPrevious()
        #expect(state.currentEntry === beta)

        var rng = FixedIndexRNG(indices: [UInt64.max])
        state.shuffleQueue(using: &rng)

        #expect(state.currentEntry === gamma)
        state.submit(.remembered, container: container, reviewSettings: .default)

        #expect(state.rememberedCount == 2)
        #expect(state.forgotCount == 1)
        #expect(state.submittedAnswers.count == 3)

        var answersByCardID: [UUID: TodayReviewState.SubmittedAnswer] = [:]
        for (index, answer) in state.submittedAnswers where index < state.queue.count {
            answersByCardID[state.queue[index].id] = answer
        }
        #expect(answersByCardID[alpha.id]?.feedback == .remembered)
        #expect(answersByCardID[beta.id]?.feedback == .forgot)
        #expect(answersByCardID[gamma.id]?.feedback == .remembered)
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
