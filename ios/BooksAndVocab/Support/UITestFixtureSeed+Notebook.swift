#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Notebook → Today Review flow fixture (`-seedFixture:notebook:reviewDeck`).
    ///
    /// Seeds a real notebook (`ui-review-notebook`) scoped over the
    /// deterministic review probe deck (reuses `makeReviewProbeDeck` — the
    /// same real-shaped entries the review flip probe measures with), so the
    /// notebook list renders a real card and the review action bar surfaces a
    /// real unlearned count. No login: today review is a fully local flow.
    @MainActor
    static func seedNotebook(_ id: String, into container: ModelContainer) {
        switch id {
        case "reviewDeck":
            seedNotebookReviewDeck(into: container)
        default:
            AppLog.app.warning("Unknown notebook fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedNotebookReviewDeck(into container: ModelContainer) {
        let notebookId = "ui-review-notebook"
        let deckSize = 8
        let context = container.mainContext
        do {
            // Idempotent re-seed: the simulator container persists across runs.
            for notebook in try context.fetch(
                FetchDescriptor<Notebook>(predicate: #Predicate { $0.remoteId == notebookId })
            ) {
                context.delete(notebook)
            }
            for entry in try context.fetch(FetchDescriptor<VocabularyEntry>()) {
                context.delete(entry)
            }

            let notebook = Notebook(remoteId: notebookId, name: "Review Flow Vocab")
            notebook.syncStatus = 1
            context.insert(notebook)

            let deck = makeReviewProbeDeck(size: deckSize)
            for entry in deck {
                entry.notebookId = notebookId
                context.insert(entry)
            }
            try context.save()
            AppLog.app.info("UI-test fixture seeded: notebook.reviewDeck (\(deck.count) cards)")
        } catch {
            AppLog.app.error("Failed to seed notebook fixture: \(error)")
        }
    }
}
#endif
