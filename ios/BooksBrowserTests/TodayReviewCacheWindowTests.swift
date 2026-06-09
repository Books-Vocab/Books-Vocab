import Testing
import Observation
@testable import BooksBrowser

@MainActor
struct TodayReviewCacheWindowTests {
    @Test func initDoesNotPrebuildWholeLargeQueue() async throws {
        let entries = (0..<40).map { index in
            let entry = VocabularyEntry(
                word: "word-\(index)",
                translation: "translation-\(index)",
                context: "A sample sentence for word \(index).",
                bookTitle: "Sample"
            )
            entry.markSynced()
            return entry
        }

        let state = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        try await Task.sleep(for: .milliseconds(120))

        #expect(state.preparedCardCache.count <= TodayReviewState.cacheLookaheadLimit + 1)
        #expect(state.currentCardForTesting != nil)
        #expect(state.nextCardForTesting != nil)
    }

    /// Regression — P0 infinite re-eval / review brick (commit 7ecb7ff5 made the
    /// render-path card lookup `mutating`). The render read
    /// (presenterState → currentCardState/nextCardState → cardCache) MUST NOT mutate
    /// any `@Observable` property: `cardCache` is an `@Observable` stored property, and
    /// a mutating lookup fires a per-render mutation (even on a cache hit, even when
    /// storage is unchanged) → SwiftUI body reads+writes the same property → infinite
    /// `TodayReviewView.body` re-eval that froze the whole app. `withObservationTracking`
    /// invokes onChange iff a property accessed during `apply` is mutated.
    @Test func renderReadDoesNotMutateObservableState() async throws {
        let entries = (0..<5).map { index -> VocabularyEntry in
            let entry = VocabularyEntry(
                word: "word-\(index)",
                translation: "translation-\(index)",
                context: "A sample sentence for word \(index).",
                bookTitle: "Sample"
            )
            entry.markSynced()
            return entry
        }

        let state = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        try await Task.sleep(for: .milliseconds(120))  // let prewarm populate the window

        var mutated = false
        withObservationTracking {
            _ = state.presenterState   // exercises currentCardState + nextCardState
        } onChange: {
            mutated = true
        }
        try await Task.sleep(for: .milliseconds(20))

        #expect(mutated == false, "render-path read mutated @Observable state → infinite re-eval loop")
        // Render reads must be pure: the cache window is unchanged by reading.
        let before = state.preparedCardCache.count
        _ = state.presenterState
        _ = state.presenterState
        #expect(state.preparedCardCache.count == before)
    }
}
