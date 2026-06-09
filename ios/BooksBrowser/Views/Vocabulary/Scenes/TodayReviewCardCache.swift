import Foundation

struct TodayReviewCardCache {
    typealias PreparedCard = TodayReviewPresenterState.CurrentCard

    private(set) var storage: [UUID: PreparedCard] = [:]

    mutating func cachedOrBuild(for entry: VocabularyEntry) -> PreparedCard? {
        if let cached = storage[entry.id] {
            PerfLog.review.tick("card.cacheHit", "w=\(entry.word)")
            return cached
        }

        let built = PerfLog.review.measure("card.cacheMiss", "w=\(entry.word)") {
            Self.build(from: [entry])
        }.value
        if let card = built[entry.id] {
            storage[entry.id] = card
            return card
        }
        return nil
    }

    mutating func rebuild(for entry: VocabularyEntry) {
        let card = CardPresentation(entry: entry)
        let compactGroups = card.activeLinkGroups.map { fullGroup in
            let limited = fullGroup.limited(to: 2)
            return TodayReviewPresenterState.LinkGroup(
                id: fullGroup.id,
                label: fullGroup.label,
                items: limited.items,
                overflowCount: limited.overflowed(relativeToFullGroup: fullGroup)
            )
        }
        let backDocument = card.document.reviewBackSubset()
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(backDocument)
        storage[entry.id] = .init(
            card: card,
            linkGroups: compactGroups,
            backDocument: backDocument,
            postExampleMetrics: metrics
        )
    }

    mutating func prewarm(
        queue: [VocabularyEntry],
        currentIndex: Int,
        lookaheadLimit: Int
    ) {
        guard !queue.isEmpty, currentIndex < queue.count else {
            storage.removeAll(keepingCapacity: false)
            return
        }

        let start = max(currentIndex - 1, 0)
        let end = min(currentIndex + lookaheadLimit, queue.count - 1)
        let visibleEntries = Array(queue[start...end])
        let visibleIDs = Set(visibleEntries.map(\.id))

        storage = storage.filter { visibleIDs.contains($0.key) }

        let missingEntries = visibleEntries.filter { storage[$0.id] == nil }
        guard !missingEntries.isEmpty else { return }
        storage.merge(Self.build(from: missingEntries)) { current, _ in current }
    }

    static func build(from entries: [VocabularyEntry]) -> [UUID: PreparedCard] {
        var cache: [UUID: PreparedCard] = [:]
        cache.reserveCapacity(entries.count)
        PerfLog.review.mark("prewarm.build", "count=\(entries.count)")
        for entry in entries {
            let (card, _) = PerfLog.review.measure("prewarm.card", "w=\(entry.word)") {
                CardPresentation(entry: entry)
            }
            let compactGroups = card.activeLinkGroups.map { fullGroup in
                let shuffled = fullGroup.shuffled()
                let limited = shuffled.limited(to: 2)
                return TodayReviewPresenterState.LinkGroup(
                    id: fullGroup.id,
                    label: fullGroup.label,
                    items: limited.items,
                    overflowCount: limited.overflowed(relativeToFullGroup: fullGroup)
                )
            }
            let backDocument = card.document.reviewBackSubset()
            let metrics = TodayReviewPresenterState.PostExampleMetrics.from(backDocument)
            cache[entry.id] = .init(
                card: card,
                linkGroups: compactGroups,
                backDocument: backDocument,
                postExampleMetrics: metrics
            )
        }
        return cache
    }
}
