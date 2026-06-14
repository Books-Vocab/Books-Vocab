#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedTodayReview(_ id: String, into container: ModelContainer) {
        switch id {
        case "deck":
            seedReviewProbeDeck(into: container)
        default:
            failFixtureSeed("Unknown todayReview fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedReviewProbeDeck(into container: ModelContainer) {
        let context = container.mainContext
        do {
            try clearVocabularyEntries(from: context)
            let seed = FixtureDatasetStore.requireReviewDeckSeed(for: .probe)
            let deck = seed.entries.map {
                makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)
            }
            for entry in deck {
                context.insert(entry)
            }
            try context.save()
            AppLog.app.info("UI-test fixture seeded: todayReview.deck size=\(deck.count)")
        } catch {
            failFixtureSeed("Failed to seed todayReview.deck fixture: \(error)")
        }
    }
}
#endif
