#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Search-flow fixture (`-seedFixture:search:vocabNotebook`).
    ///
    /// Seeds everything the vocabulary search flow asserts on:
    /// - a notebook (`ui-search-notebook`) reachable from the notebook list,
    /// - the curated demo vocabulary (real words / translations / contexts /
    ///   graph links shipped to the demo account — affect, effect, complement,
    ///   compliment, … — NOT mock rows) re-scoped into that notebook so the
    ///   `KGVocabView` knowledge-list query has real searchable entries,
    /// - an authenticated session (the search field only renders when
    ///   `authManager.isLoggedIn`).
    ///
    /// Other tabs are covered by their own fixture domains; this fixture
    /// deliberately does not touch them (hot-spot ownership contract in
    /// docs/sop/ui_flow_evidence.md).
    @MainActor
    static func seedSearch(_ id: String, into container: ModelContainer) {
        switch id {
        case "vocabNotebook":
            seedSearchVocabNotebook(into: container)
        default:
            AppLog.app.warning("Unknown search fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedSearchVocabNotebook(into container: ModelContainer) {
        let notebookId = "ui-search-notebook"
        let context = container.mainContext
        do {
            try clearSearchFixtures(from: context, notebookId: notebookId)

            let notebook = Notebook(remoteId: notebookId, name: "Search Flow Vocab")
            notebook.syncStatus = 1
            context.insert(notebook)

            // Real curated learning content (same provider the demo account
            // ships), re-scoped to the search notebook so the notebook-scoped
            // knowledge list renders exactly this deterministic word set.
            DemoDataProvider.injectDemoEntries(into: container)
            let entries = try context.fetch(
                FetchDescriptor<VocabularyEntry>(
                    predicate: #Predicate { $0.isDemoEntry == true }
                )
            )
            for entry in entries {
                entry.notebookId = notebookId
            }
            try context.save()

            // The search field is gated on a logged-in session. Only log in
            // when no earlier fixture already did, so combining fixtures never
            // triggers the account-switch wipe.
            if !AuthManager.shared.isLoggedIn {
                seedSignedInLoginFromWorld()
            }
            AppLog.app.info("UI-test fixture seeded: search.vocabNotebook (\(entries.count) entries)")
        } catch {
            AppLog.app.error("Failed to seed search fixture: \(error)")
        }
    }

    /// Idempotent re-seed: the simulator container persists across runs.
    @MainActor
    private static func clearSearchFixtures(from context: ModelContext, notebookId: String) throws {
        for notebook in try context.fetch(
            FetchDescriptor<Notebook>(predicate: #Predicate { $0.remoteId == notebookId })
        ) {
            context.delete(notebook)
        }
        for entry in try context.fetch(
            FetchDescriptor<VocabularyEntry>(predicate: #Predicate { $0.isDemoEntry == true })
        ) {
            context.delete(entry)
        }
        try context.save()
    }
}
#endif
