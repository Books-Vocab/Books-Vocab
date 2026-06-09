import Testing
@testable import BooksAndVocab

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

    /// Regression guard for the P0 review brick (commit 7ecb7ff5): the render-path
    /// card lookup must stay a PURE, non-`mutating` read. The original bug made the
    /// lookup `mutating` and stored onto the `@Observable cardCache` from the render
    /// path, so every `TodayReviewView.body` read wrote the same observed property →
    /// infinite re-eval that froze the whole app.
    ///
    /// Scope note (learned the hard way via a revert check): the *exact* hit-path
    /// failure — a spurious observation notification on an unchanged store — is NOT
    /// observable from a unit test. `withObservationTracking` only arms `onChange`
    /// for mutations that happen *after* its `apply` closure returns, but the buggy
    /// mutation fires *during* the render read (the synthesized `_modify` accessor
    /// runs `willSet`/`didSet` inline). A `withObservationTracking`-based assertion
    /// therefore passes whether or not the bug is present (false green). So this locks
    /// the enforceable invariant instead — the render lookup neither writes storage
    /// nor builds on a miss — and the behavioral proof is the on-device run (press
    /// 複習 → no freeze). If a refactor makes the render lookup store again, the
    /// `storage` count assertions below go red.
    @Test func renderLookupIsPureAndDoesNotStore() {
        var cache = TodayReviewCardCache()
        let entry = VocabularyEntry(
            word: "lucid",
            translation: "清晰",
            context: "A lucid sentence.",
            bookTitle: "Sample"
        )
        entry.markSynced()

        // Render-path lookup on an empty cache: a miss must NOT build-and-store
        // (that store is what the @Observable property would notify on, per render).
        let before = cache.storage.count
        let miss = cache.cached(for: entry)
        #expect(miss == nil)
        #expect(cache.storage.count == before, "render lookup miss wrote to the observed cache")

        // Action-path build (allowed to store) then a hit: still no duplication, and
        // repeated render-path reads stay pure.
        cache.rebuild(for: entry)
        #expect(cache.storage.count == before + 1)
        let hit1 = cache.cached(for: entry)
        let hit2 = cache.cached(for: entry)
        #expect(hit1 != nil)
        #expect(hit2 != nil)
        #expect(cache.storage.count == before + 1, "render lookup hit mutated the observed cache")
    }
}
