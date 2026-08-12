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
            statsProjectionClock = makeStatsProjectionClock(
                for: .shellNavigation,
                latestReviewedAt: seed.reviewHistory.map(\.reviewedAt).max()
            )
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

extension UITestFixtureSeed {
    /// Overview/Stats fixture bridge. The payload is always resolved from the
    /// injected kg.fixture.dataset.v2 document; this argument only selects the
    /// named vocabulary seed and never creates a second data source.
    @MainActor
    static func seedVocabulary(_ id: String, into container: ModelContainer) {
        guard let fixtureID = UIWorldVocabularyFixtureID(rawValue: id) else {
            failFixtureSeed("Unknown vocabulary fixture ID: \(id)")
        }

        let seed: UIWorldVocabularySeed
        if fixtureID == .reviewCalendarDense {
            seed = FixtureDatasetStore.requireVocabularySeed(for: .reviewCalendarDense)
        } else {
            seed = FixtureDatasetStore.requireVocabularySeed(for: fixtureID)
        }
        let context = container.mainContext
        do {
            if fixtureID == .reviewCalendarDense {
                try clearReviewCalendarFixtures(from: context)
                _ = try FixtureDatasetStore.materializeEvidenceFixture()
            } else {
                try clearVocabularyEntries(from: context)
            }
            _ = try insertVocabularySeed(seed, into: context)
            if !AuthManager.shared.isLoggedIn {
                seedSignedInLoginFromWorld()
            }

            statsProjectionClock = makeStatsProjectionClock(
                for: fixtureID,
                latestReviewedAt: seed.reviewHistory.map(\.reviewedAt).max()
            )
            AppLog.app.info("UI-test fixture seeded: vocabulary.\(fixtureID.rawValue) (\(seed.entries.count) entries, \(seed.reviewHistory.count) reviews)")
        } catch {
            failFixtureSeed("Failed to seed vocabulary.\(fixtureID.rawValue): \(error)")
        }
    }

    /// Every UI fixture gets an explicit UTC projection clock. `vocabListLong`
    /// uses an explicit pre-due fallback when no review history exists, so the
    /// zero-forecast counterexample is deterministic. A fixture with review
    /// history anchors to that history and exercises overdue-to-today folding.
    @MainActor
    static func makeStatsProjectionClock(
        for fixtureID: UIWorldVocabularyFixtureID,
        latestReviewedAt: Date?
    ) -> StatsProjectionClock {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? calendar.timeZone
        let fallbackComponents: DateComponents
        switch fixtureID {
        case .vocabListLong:
            fallbackComponents = DateComponents(
                calendar: calendar,
                timeZone: calendar.timeZone,
                year: 2025,
                month: 12,
                day: 20,
                hour: 12
            )
        default:
            fallbackComponents = DateComponents(
                calendar: calendar,
                timeZone: calendar.timeZone,
                year: 2026,
                month: 6,
                day: 1,
                hour: 12
            )
        }
        let fallback = calendar.date(from: fallbackComponents) ?? Date(timeIntervalSince1970: 0)
        return StatsProjectionClock(now: latestReviewedAt ?? fallback, calendar: calendar)
    }
}
#endif
