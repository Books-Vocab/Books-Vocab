import CoreGraphics
import Testing
@testable import BooksAndVocab

/// #2133: a pending-link update must not reset the open card's measurements.
/// `TodayReviewCardCache.rebuild` builds a fresh `ReviewCardMeasurementCache`, so a
/// card on screen would re-solve its layout from defaults and jump for a frame.
@Suite("Review card pending-link refresh (#2133)")
@MainActor
struct ReviewCardPendingRefreshTests {
    private func entry() -> VocabularyEntry {
        let entry = VocabularyEntry(word: "lucid", translation: "清晰", context: "A lucid thought.", bookTitle: "Book")
        entry.kgCardId = "card-lucid"
        entry.markSynced()
        return entry
    }

    private func key(_ section: ReviewCardLayoutSolver.Section, card: String) -> ReviewCardMeasurementKey {
        ReviewCardMeasurementKey(cardKey: card, face: .back, section: section, widthBucket: 393, dynamicType: "large")
    }

    private func pending(_ state: KGCardLinkSummary.CreationState, jobKey: String = "card-lucid|lum") -> KGCardLinkSummary {
        .pendingCreation(jobKey: jobKey, word: "lum", state: state)
    }

    @Test("creating -> failed keeps the measurement cache and every measured height")
    func stateFlipKeepsMeasurements() throws {
        let entry = entry()
        var cache = TodayReviewCardCache()
        cache.rebuild(for: entry)
        cache.refreshLinks(for: entry, pendingLinks: [pending(.creating)])
        let before = try #require(cache.storage[entry.id])
        let cardKey = before.card.reviewCardKey
        before.measurementCache.record(120, for: key(.graphLinks, card: cardKey), level: .natural)
        before.measurementCache.record(80, for: key(.example, card: cardKey), level: .natural)

        cache.refreshLinks(for: entry, pendingLinks: [pending(.failed)])

        let after = try #require(cache.storage[entry.id])
        #expect(after.measurementCache === before.measurementCache, "state flip must not rebuild the cache")
        #expect(after.measurementCache.value(for: key(.graphLinks, card: cardKey), level: .natural) == 120)
        #expect(after.measurementCache.value(for: key(.example, card: cardKey), level: .natural) == 80)
        let items = after.linkGroups.flatMap(\.items)
        #expect(items.map(\.pendingCreationState) == [.failed], "the new state is what the strip now shows")
    }

    @Test("a job appearing or disappearing re-measures only the graph-links section")
    func itemSetChangeInvalidatesOnlyGraphLinks() throws {
        let entry = entry()
        var cache = TodayReviewCardCache()
        cache.rebuild(for: entry)
        let initial = try #require(cache.storage[entry.id])
        let cardKey = initial.card.reviewCardKey
        let measurements = initial.measurementCache
        measurements.record(120, for: key(.graphLinks, card: cardKey), level: .natural)
        measurements.record(90, for: key(.graphLinks, card: cardKey + "|links-expanded:shares_usage"), level: .compact)
        measurements.record(80, for: key(.example, card: cardKey), level: .natural)

        cache.refreshLinks(for: entry, pendingLinks: [pending(.creating)])

        let added = try #require(cache.storage[entry.id])
        #expect(added.measurementCache === measurements)
        #expect(added.measurementCache.value(for: key(.graphLinks, card: cardKey), level: .natural) == nil)
        #expect(
            added.measurementCache.value(
                for: key(.graphLinks, card: cardKey + "|links-expanded:shares_usage"), level: .compact
            ) == nil,
            "expanded variants of the strip are stale too"
        )
        #expect(added.measurementCache.value(for: key(.example, card: cardKey), level: .natural) == 80)
        #expect(added.linkGroups.flatMap(\.items).count == 1)

        added.measurementCache.record(130, for: key(.graphLinks, card: cardKey), level: .natural)
        cache.refreshLinks(for: entry, pendingLinks: [])
        let removed = try #require(cache.storage[entry.id])
        #expect(removed.measurementCache.value(for: key(.graphLinks, card: cardKey), level: .natural) == nil)
        #expect(removed.measurementCache.value(for: key(.example, card: cardKey), level: .natural) == 80)
        #expect(removed.linkGroups.isEmpty)
    }

    @Test("existing links keep their on-screen order when a pending item joins")
    func existingOrderIsStable() throws {
        let entry = entry()
        let links = (0..<4).map {
            KGCardLinkSummary(
                id: "l\($0)", cardId: "c\($0)", word: "w\($0)", kind: "shares_usage",
                label: "x", confidence: 1, reason: "r"
            )
        }
        entry.graphLinksByKind = ["shares_usage": links]
        let pendingLink = pending(.creating)
        for _ in 0..<20 {
            var cache = TodayReviewCardCache()
            // `prewarm` builds with the display shuffle, so the order differs per run.
            cache.prewarm(queue: [entry], currentIndex: 0, lookaheadLimit: 0)
            let before = try #require(cache.storage[entry.id]).linkGroups.flatMap(\.items).map(\.id)
            #expect(Set(before) == Set(links.map(\.id)))

            cache.refreshLinks(for: entry, pendingLinks: [pendingLink])

            let after = try #require(cache.storage[entry.id]).linkGroups.flatMap(\.items).map(\.id)
            #expect(after == [pendingLink.id] + before)
        }
    }

    @Test("an uncached card is left to the next build")
    func uncachedCardIsNotBuilt() {
        var cache = TodayReviewCardCache()
        cache.refreshLinks(for: entry(), pendingLinks: [pending(.creating)])
        #expect(cache.storage.isEmpty)
    }
}
