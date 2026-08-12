#if os(iOS) && DEBUG
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedExplore(_ id: String, into container: ModelContainer) {
        let specs: [SharedDeckCatalogFixtures.DeckSpec]
        switch id {
        case "loaded", "loading", "retry":
            specs = SharedDeckCatalogFixtures.populated
        case "empty", "empty-counterexample":
            specs = []
        case "retry-counterexample":
            specs = SharedDeckCatalogFixtures.counterexample
        default:
            failFixtureSeed("Unknown explore fixture ID: \(id)")
        }

        let context = container.mainContext
        do {
            for deck in try context.fetch(FetchDescriptor<SharedDeck>()) {
                context.delete(deck)
            }
            for (index, spec) in specs.enumerated() {
                let deck = SharedDeck(remoteId: spec.remoteId, title: spec.title)
                deck.authorLabel = spec.author
                deck.isOfficial = spec.isOfficial
                deck.category = spec.category
                deck.languagePair = spec.languagePair
                deck.tags = spec.tags
                deck.cardCount = spec.cardCount
                deck.downloadCount = spec.downloadCount
                deck.ratingAvg = spec.ratingAvg
                deck.ratingCount = spec.ratingCount
                deck.color = spec.color
                deck.coverPattern = spec.coverPattern
                deck.sortOrder = index
                context.insert(deck)
            }
            try context.save()
        } catch {
            failFixtureSeed("Failed to seed Explore fixture \(id): \(error)")
        }
    }
}
#endif
