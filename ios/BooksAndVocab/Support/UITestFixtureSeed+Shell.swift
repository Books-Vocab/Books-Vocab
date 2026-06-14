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
            AppLog.app.warning("Unknown shell fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedShellNavigation(into container: ModelContainer) {
        let notebookId = "ui-shell-notebook"
        let context = container.mainContext
        do {
            try clearShellFixtures(from: context, notebookId: notebookId)

            let notebook = Notebook(remoteId: notebookId, name: "Shell Flow Vocab")
            notebook.syncStatus = 1
            context.insert(notebook)

            // Reuse the curated demo entries (real words / translations /
            // contexts / graph links shipped to the demo account) instead of
            // inventing mock rows, then scope them to the shell notebook.
            DemoDataProvider.injectDemoEntries(into: container)
            let entries = try context.fetch(
                FetchDescriptor<VocabularyEntry>(
                    predicate: #Predicate { $0.isDemoEntry == true }
                )
            )
            for entry in entries {
                entry.notebookId = notebookId
            }

            // Review history over the past week: consecutive days build a real
            // streak + heatmap so the overview phase resolves to `.content`.
            let calendar = Calendar.current
            let now = Date()
            for (offset, entry) in entries.prefix(10).enumerated() {
                let reviewedAt = calendar.date(
                    byAdding: .day,
                    value: -(offset % 7),
                    to: now
                ) ?? now
                let record = ReviewRecord(
                    word: entry.word,
                    entryID: entry.id,
                    feedback: offset.isMultiple(of: 3) ? 0 : 1,
                    reviewedAt: reviewedAt,
                    kgCardId: entry.kgCardId
                )
                record.notebookId = notebookId
                context.insert(record)
            }

            try context.save()

            // Overview + notebook list need an authenticated session. The
            // isolated auth session starts logged out; only log in when no
            // earlier fixture (e.g. podcast playablePreview) already did, so
            // combining fixtures never triggers the account-switch wipe.
            if !AuthManager.shared.isLoggedIn {
                seedSignedInLoginFromWorld()
            }
            AppLog.app.info("UI-test fixture seeded: shell.navigation (\(entries.count) entries)")
        } catch {
            AppLog.app.error("Failed to seed shell fixture: \(error)")
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
            FetchDescriptor<VocabularyEntry>(predicate: #Predicate { $0.isDemoEntry == true })
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
