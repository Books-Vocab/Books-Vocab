#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Shell/Tab navigation flow fixture (`-seedFixture:shell:navigation`).
    ///
    /// Seeds the data the notebook + overview tabs need to render REAL content:
    /// - a notebook (`ui-shell-notebook`) so NotebookListView shows a card,
    /// - the curated demo vocabulary (real learning content, already `synced`)
    ///   re-scoped into that notebook so StatsPresenter's `syncedEntries` query
    ///   is non-empty,
    /// - a week of `ReviewRecord` history so the overview summary (streak /
    ///   heatmap / forecast) is non-empty → `VocabScenePhase.content`.
    ///
    /// Bookshelf/podcast tabs are covered by their own fixture domains; this
    /// fixture deliberately does not touch them (hot-spot ownership contract in
    /// docs/sop/ui_flow_evidence.md).
    @MainActor
    static func seedShell(_ id: String, into container: ModelContainer) {
        switch id {
        case "navigation":
            seedShellNavigation(into: container)
        default:
            failFixtureSeed("Unknown shell fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedShellNavigation(into container: ModelContainer) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: .shellNavigation)
        let notebookId = seed.notebookRemoteId
        let context = container.mainContext
        do {
            try clearShellFixtures(from: context, notebookId: notebookId)

            let entries = try insertVocabularySeed(seed, into: context)

            // Overview + notebook list need an authenticated session. The
            // isolated auth session starts logged out; only log in when no
            // earlier fixture (e.g. podcast playablePreview) already did, so
            // combining fixtures never triggers the account-switch wipe.
            if !AuthManager.shared.isLoggedIn {
                seedSignedInLoginFromWorld()
            }
            AppLog.app.info("UI-test fixture seeded: shell.navigation (\(entries.count) entries)")
        } catch {
            failFixtureSeed("Failed to seed shell.navigation fixture: \(error)")
        }
    }

    /// Idempotent re-seed: the simulator container persists across runs.
    @MainActor
    private static func clearShellFixtures(from context: ModelContext, notebookId: String) throws {
        for notebook in try context.fetch(
            FetchDescriptor<Notebook>(predicate: #Predicate { $0.remoteId == notebookId })
        ) {
            context.delete(notebook)
        }
        for entry in try context.fetch(
            FetchDescriptor<VocabularyEntry>(predicate: #Predicate { $0.notebookId == notebookId })
        ) {
            context.delete(entry)
        }
        for record in try context.fetch(
            FetchDescriptor<ReviewRecord>(predicate: #Predicate { $0.notebookId == notebookId })
        ) {
            context.delete(record)
        }
        try context.save()
    }
}
#endif
