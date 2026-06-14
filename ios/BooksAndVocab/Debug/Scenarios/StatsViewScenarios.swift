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
                StatsViewScene(fixture: .populated)
            }
            Scenario("Empty", layout: .fill) {
                StatsViewScene(fixture: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum StatsViewFixture {
    case populated
    case empty

    var vocabularyID: UIWorldVocabularyFixtureID {
        switch self {
        case .populated:
            return .statsPopulated
        case .empty:
            return .statsEmpty
        }
    }

    var expected: StatsViewExpectedShape {
        switch self {
        case .populated:
            return .init(visibleEntries: .atLeast(8), reviewRecords: .atLeast(12))
        case .empty:
            return .init(visibleEntries: .exactly(0), reviewRecords: .exactly(0))
        }
    }
}

private struct StatsViewExpectedShape {
    enum Count {
        case exactly(Int)
        case atLeast(Int)

        func validate(_ actual: Int, label: String, fixtureID: UIWorldVocabularyFixtureID) {
            switch self {
            case .exactly(let expected):
                precondition(
                    actual == expected,
                    "UI World vocabulary.\(fixtureID.rawValue) expected exactly \(expected) \(label), got \(actual)"
                )
            case .atLeast(let minimum):
                precondition(
                    actual >= minimum,
                    "UI World vocabulary.\(fixtureID.rawValue) expected at least \(minimum) \(label), got \(actual)"
                )
            }
        }
    }

    let visibleEntries: Count
    let reviewRecords: Count
}

private enum StatsViewTime {
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
}

// MARK: - Scene harness

/// `@MainActor` body so the in-memory container is seeded and env-default
/// services resolve on the main actor before `@Query` reads.
private struct StatsViewScene: View {
    let container: ModelContainer
    let initialSummary: StatsPresentation.Summary

    init(fixture: StatsViewFixture) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)
        do {
            let container = try ModelContainer(
                for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let entries = try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)
            let visibleEntries = entries.filter(\.shouldAppearInKnowledgeList)
            fixture.expected.visibleEntries.validate(
                visibleEntries.count,
                label: "visible stats entries",
                fixtureID: fixture.vocabularyID
            )

            let records = try container.mainContext.fetch(FetchDescriptor<ReviewRecord>())
            fixture.expected.reviewRecords.validate(
                records.count,
                label: "review records",
                fixtureID: fixture.vocabularyID
            )

            self.container = container
            self.initialSummary = StatsPresentation.buildSummary(
                from: visibleEntries,
                reviewRecords: records,
                forecastDays: 14,
                now: StatsViewTime.fixedNow
            )
        } catch {
            preconditionFailure("Failed to materialize UI World vocabulary.\(fixture.vocabularyID.rawValue) for Stats View catalog: \(error)")
        }
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
    /// `StatsViewTime.fixedNow`, making the presenter's `@Query`-driven
    /// summary recompute deterministic across catalog runs.
    private static let frozenStore: ReviewSettingsStore = {
        var settings = ReviewSettings.default
        settings.isProgressPaused = true
        settings.progressPausedAt = StatsViewTime.fixedNow
        return ReviewSettingsStore(previewSettings: settings)
    }()
}
#endif
