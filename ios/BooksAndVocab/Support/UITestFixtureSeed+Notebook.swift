#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Notebook → Today Review flow fixture (`-seedFixture:notebook:reviewDeck`).
    ///
    /// Seeds the UI World-owned notebook review deck so the notebook list
    /// renders a real card and the review action bar surfaces a real unlearned
    /// count. No login: today review is a fully local flow.
    @MainActor
    static func seedNotebook(_ id: String, into container: ModelContainer) {
        switch id {
        case "reviewDeck":
            seedNotebookReviewDeck(into: container)
        default:
            failFixtureSeed("Unknown notebook fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedNotebookReviewDeck(into container: ModelContainer) {
        let seed = FixtureDatasetStore.requireReviewDeckSeed(for: .notebookReviewDeck)
        let notebookId = seed.notebookRemoteId
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

            let notebook = Notebook(remoteId: notebookId, name: seed.notebookName)
            notebook.syncStatus = seed.notebookSyncStatus
            context.insert(notebook)

            let deck = seed.entries.map {
                makeVocabularyEntry(from: $0, notebookId: notebookId)
            }
            for entry in deck {
                context.insert(entry)
            }
            try context.save()
            AppLog.app.info("UI-test fixture seeded: notebook.reviewDeck (\(deck.count) cards)")
        } catch {
            failFixtureSeed("Failed to seed notebook.reviewDeck fixture: \(error)")
        }
    }
}
#endif
