import Testing
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
}
