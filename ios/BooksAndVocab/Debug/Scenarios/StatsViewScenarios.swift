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
            // 關聯圖 card hosts a WKWebView (invisible to `layer.render(in:)`
            // snapshots), so the populated scene is wrapped in
            // CatalogGraphSnapshotScene — active only when the seed actually
            // carries graph links (link-less datasets render the empty card,
            // which needs no freeze). Empty scene has no webview by
            // construction.
            Scenario("Populated", layout: .fill) { context in
                StatsViewPopulatedScene(context: context)
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

/// Internal (not private) so unit tests can pin the anchor derivation.
enum StatsViewTime {
    /// Deterministic fallback anchor for seeds with no review events（statsEmpty）
    /// — nothing to derive from, and wall-clock `Date()` would re-introduce
    /// snapshot drift.
    static let emptySeedFallback: Date = {
        var comps = DateComponents()
        comps.year = 2026
        comps.month = 6
        comps.day = 1
        comps.hour = 12
        return Calendar.current.date(from: comps) ?? Date()
    }()

    /// Frozen "today" so streak / heatmap / forecast snapshots stay stable across
    /// catalog re-runs (the presenter is otherwise `Date()`-relative, which made
    /// this group's reference PNGs drift on every capture). Derived from the
    /// seed's latest review event (noon of that day): a hard-coded date left the
    /// 「複習預測/今日到期」 cards permanently 0 once the seed narrative anchored
    /// on a different day.
    static func anchor(latestReviewedAt: Date?) -> Date {
        guard let latest = latestReviewedAt else { return emptySeedFallback }
        return Calendar.current.date(bySettingHour: 12, minute: 0, second: 0, of: latest) ?? latest
    }
}

// MARK: - Scene harness

/// Populated scene + snapshot freezer, assembled once in `init` (a freezer
/// must not be re-created on body re-evaluation — it arms the scenario's
/// SnapshotWaiter).
private struct StatsViewPopulatedScene: View {
    private let content: CatalogGraphSnapshotScene<StatsViewScene>

    init(context: ScenarioContext) {
        let scene = StatsViewScene(fixture: .populated)
        self.content = CatalogGraphSnapshotScene(context: context, isActive: scene.hasGraphLinks) {
            scene
        }
    }

    var body: some View { content }
}

/// `@MainActor` body so the in-memory container is seeded and env-default
/// services resolve on the main actor before `@Query` reads.
private struct StatsViewScene: View {
    let container: ModelContainer
    let initialSummary: StatsPresentation.Summary
    /// 關聯圖 card links, derived from the same UI World seed as the entries
    /// (manifest is the single link source; empty when the dataset carries no
    /// links, which legitimately renders the card's empty state).
    let graphLinks: [KGGraphLink]
    private let frozenStore: ReviewSettingsStore

    var hasGraphLinks: Bool { !graphLinks.isEmpty }

    init(fixture: StatsViewFixture) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)
        do {
            let container = try ModelContainer(
                for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            // Seed as pending changes only (no broadcast NSManagedObjectContextDidSave).
            // In the async catalog web-view pass this scene renders after the full
            // ~1300-snapshot main pass, whose @Query scenes leave dangling observers
            // once their ModelContainers deallocate; a committing save() here posts a
            // process-wide didSave that those dangling observers trap on
            // (EXC_BREAKPOINT in _SwiftData_SwiftUI). @Query and fetch both see pending
            // inserts, so the stats + 關聯圖 render identically without the save.
            container.mainContext.autosaveEnabled = false
            let entries = try UITestFixtureSeed.insertVocabularySeed(
                seed, into: container.mainContext, save: false
            )
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

            let frozenNow = StatsViewTime.anchor(latestReviewedAt: records.map(\.reviewedAt).max())
            self.container = container
            self.graphLinks = UIWorldGraphLinks.makeGraphLinks(
                from: visibleEntries,
                fixtureID: fixture.vocabularyID
            )
            self.initialSummary = StatsPresentation.buildSummary(
                from: visibleEntries,
                reviewRecords: records,
                forecastDays: 14,
                now: frozenNow
            )
            self.frozenStore = Self.makeFrozenStore(now: frozenNow)
        } catch {
            preconditionFailure("Failed to materialize UI World vocabulary.\(fixture.vocabularyID.rawValue) for Stats View catalog: \(error)")
        }
    }

    var body: some View {
        AppThemeContainer {
            StatsPresenter(
                filter: NotebookFilter(),
                initialSummary: initialSummary,
                initialGraphLinks: graphLinks,
                shouldLoadGraphData: false
            )
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
        // The presenter's `.task` recomputes `summary` using
        // `reviewSettingsStore.settings.reviewReferenceDate()` as "now", which is
        // live `Date()` unless progress is paused — that recompute would override
        // the frozen `initialSummary` and re-introduce date drift. Inject a paused
        // store anchored at the seed-derived frozen now so the live recompute is
        // deterministic too.
        .environment(\.reviewSettingsStore, frozenStore)
    }

    /// A paused `ReviewSettingsStore` whose reference date is pinned to the
    /// seed-derived frozen now, making the presenter's `@Query`-driven
    /// summary recompute deterministic across catalog runs.
    private static func makeFrozenStore(now: Date) -> ReviewSettingsStore {
        var settings = ReviewSettings.default
        settings.isProgressPaused = true
        settings.progressPausedAt = now
        return ReviewSettingsStore(previewSettings: settings)
    }
}
#endif
