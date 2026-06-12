#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `StatsPresenter` (學習統計儀表板).
///
/// `StatsPresenter` is `@Query`-backed: it reads synced `VocabularyEntry`
/// (`syncStatus == 1 && actionType != "delete"`) and recent `ReviewRecord`
/// (`reviewedAt > 6-months-ago`). Each scenario seeds a fresh in-memory
/// `ModelContainer` with synthetic synced entries + review records spread across
/// recent days (so streak / heatmap / forecast cards populate) inside a
/// `@MainActor` View body — env-default services (`KGService`, auth, review
/// settings store, toast coordinator) resolve on the main actor before `@Query`
/// reads. The summary `.task` is pure local computation (deterministic). The
/// graph `.task` no-ops to the empty graph card when logged out (avoids
/// WKWebView / network), which is the intended catalog rendering.
enum StatsViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Stats View") {
            Scenario("Populated", layout: .fill) {
                StatsViewScene(
                    entries: StatsViewFixtures.entries,
                    records: StatsViewFixtures.records
                )
            }
            Scenario("Empty", layout: .fill) {
                StatsViewScene(entries: [], records: [])
            }
        }
    }
}

// MARK: - Fixtures

private enum StatsViewFixtures {
    /// Frozen "today" so streak / heatmap / forecast snapshots stay stable across
    /// catalog re-runs (the presenter is otherwise `Date()`-relative, which made
    /// this group's reference PNGs drift on every capture). All review records and
    /// the seeded summary derive from this anchor — precedent:
    /// `VocabCalendarGridScenarios.fixedMonth()`.
    static let fixedNow: Date = {
        var comps = DateComponents()
        comps.year = 2026
        comps.month = 6
        comps.day = 1
        comps.hour = 12
        return Calendar.current.date(from: comps) ?? Date()
    }()

    /// Builds a synced (non-deleted) entry so it passes the `syncStatus == 1 &&
    /// actionType != "delete"` query predicate.
    static func synced(
        word: String,
        translation: String,
        partOfSpeech: String? = "n."
    ) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: translation,
            context: "It was pure \(word) — a moment that lingered in memory.",
            explanation: "A short contextual gloss for \(word).",
            partOfSpeech: partOfSpeech,
            bookTitle: "Sample Book",
            chapterTitle: "第一章"
        )
        entry.syncStatus = VocabularySyncState.synced.rawValue
        entry.actionType = VocabularySyncAction.add.rawValue
        return entry
    }

    static var entries: [VocabularyEntry] {
        [
            synced(word: "serendipity", translation: "機緣巧合"),
            synced(word: "ephemeral", translation: "短暫的", partOfSpeech: "adj."),
            synced(word: "petrichor", translation: "雨後泥土香"),
            synced(word: "ineffable", translation: "難以言喻的", partOfSpeech: "adj."),
            synced(word: "quintessential", translation: "典型的", partOfSpeech: "adj."),
            synced(word: "luminous", translation: "發光的", partOfSpeech: "adj."),
            synced(word: "cadence", translation: "節奏"),
            synced(word: "solitude", translation: "獨處"),
        ]
    }

    /// Review records spread across the last ~30 days (with a recent unbroken
    /// run for streak) so heatmap / streak / forecast cards have signal.
    static var records: [ReviewRecord] {
        let calendar = Calendar.current
        let now = fixedNow
        let words = entries.map(\.word)
        var result: [ReviewRecord] = []

        // Recent 10-day unbroken streak: a few reviews per day.
        for dayOffset in 0..<10 {
            guard let day = calendar.date(byAdding: .day, value: -dayOffset, to: now) else { continue }
            let reviewsThatDay = 2 + (dayOffset % 3)
            for i in 0..<reviewsThatDay {
                let word = words[(dayOffset + i) % words.count]
                result.append(
                    ReviewRecord(
                        word: word,
                        entryID: UUID(),
                        feedback: i % 4 == 0 ? 0 : 1,
                        reviewedAt: calendar.date(byAdding: .hour, value: -i, to: day) ?? day
                    )
                )
            }
        }

        // Sparser activity further back to fill the heatmap.
        for dayOffset in stride(from: 12, through: 30, by: 2) {
            guard let day = calendar.date(byAdding: .day, value: -dayOffset, to: now) else { continue }
            let word = words[dayOffset % words.count]
            result.append(
                ReviewRecord(
                    word: word,
                    entryID: UUID(),
                    feedback: 1,
                    reviewedAt: day
                )
            )
        }

        return result
    }
}

// MARK: - Scene harness

/// `@MainActor` body so the in-memory container is seeded and env-default
/// services resolve on the main actor before `@Query` reads.
private struct StatsViewScene: View {
    let container: ModelContainer
    let initialSummary: StatsPresentation.Summary

    init(entries: [VocabularyEntry], records: [ReviewRecord]) {
        let container = try! ModelContainer(
            for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext
        for entry in entries {
            context.insert(entry)
        }
        for record in records {
            context.insert(record)
        }
        try? context.save()
        self.container = container
        self.initialSummary = StatsPresentation.buildSummary(
            from: entries,
            reviewRecords: records,
            forecastDays: 14,
            now: StatsViewFixtures.fixedNow
        )
    }

    var body: some View {
        AppThemeContainer {
            StatsPresenter(
                filter: NotebookFilter(),
                initialSummary: initialSummary
            )
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
        // The presenter's `.task` recomputes `summary` using
        // `reviewSettingsStore.settings.reviewReferenceDate()` as "now", which is
        // live `Date()` unless progress is paused — that recompute would override
        // the frozen `initialSummary` and re-introduce date drift. Inject a paused
        // store anchored at `fixedNow` so the live recompute is deterministic too.
        .environment(\.reviewSettingsStore, StatsViewScene.frozenStore)
    }

    /// A paused `ReviewSettingsStore` whose reference date is pinned to
    /// `StatsViewFixtures.fixedNow`, making the presenter's `@Query`-driven
    /// summary recompute deterministic across catalog runs.
    private static let frozenStore: ReviewSettingsStore = {
        var settings = ReviewSettings.default
        settings.isProgressPaused = true
        settings.progressPausedAt = StatsViewFixtures.fixedNow
        return ReviewSettingsStore(previewSettings: settings)
    }()
}
#endif
