#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `ReviewCalendarPresenter`.
///
/// The presenter is fully `@Query`-driven (SwiftData), so each scenario materializes
/// UI World vocabulary seeds, including `reviewHistory`, into an in-memory
/// `ModelContainer`. Missing seeds, row-count drift, or save failure fail at
/// catalog construction time.
enum ReviewCalendarScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Review Calendar Presenter") {
            Scenario("Recent review history", layout: .fill) {
                ReviewCalendarScene(fixture: .recent)
            }
            Scenario("Heavy month streak", layout: .fill) {
                ReviewCalendarScene(fixture: .dense)
            }
            Scenario("Empty DB", layout: .fill) {
                ReviewCalendarScene(fixture: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum ReviewCalendarFixture {
    case recent
    case dense
    case empty

    var vocabularyID: UIWorldVocabularyFixtureID {
        switch self {
        case .recent:
            return .statsPopulated
        case .dense:
            return .reviewCalendarDense
        case .empty:
            return .statsEmpty
        }
    }

    var expectedReviewRecords: ReviewCalendarExpectedCount {
        switch self {
        case .recent:
            return .atLeast(12)
        case .dense:
            return .atLeast(70)
        case .empty:
            return .exactly(0)
        }
    }
}

private enum ReviewCalendarExpectedCount {
    case exactly(Int)
    case atLeast(Int)

    func validate(_ actual: Int, fixtureID: UIWorldVocabularyFixtureID) {
        switch self {
        case .exactly(let expected):
            precondition(
                actual == expected,
                "UI World vocabulary.\(fixtureID.rawValue) expected exactly \(expected) review records, got \(actual)"
            )
        case .atLeast(let minimum):
            precondition(
                actual >= minimum,
                "UI World vocabulary.\(fixtureID.rawValue) expected at least \(minimum) review records, got \(actual)"
            )
        }
    }
}

// MARK: - Scene harness

private struct ReviewCalendarScene: View {
    private let container: ModelContainer

    init(fixture: ReviewCalendarFixture) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)
        do {
            let container = try ModelContainer(
                for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            _ = try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)

            let records = try container.mainContext.fetch(FetchDescriptor<ReviewRecord>())
            fixture.expectedReviewRecords.validate(records.count, fixtureID: fixture.vocabularyID)
            self.container = container
        } catch {
            preconditionFailure("Failed to materialize UI World vocabulary.\(fixture.vocabularyID.rawValue) for ReviewCalendarScenarios: \(error)")
        }
    }

    var body: some View {
        AppThemeContainer {
            ReviewCalendarPresenter()
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
