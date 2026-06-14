#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `TodayReviewPhaseView` — the 4-state outer matrix
/// (loading / empty / failure / session) that wraps the TodayReview modal.
///
/// Uses the public `init(phase:onClose:)` seam. The `.session` phase delegates
/// to `TodayReviewView`, so session scenarios materialize UI World `reviewDeck.*`
/// seeds into an in-memory SwiftData container and take auth from UI World
/// `auth.signedIn`. Missing seed, auth drift, row-count drift, or save failure
/// fail at catalog construction time.
enum TodayReviewPhaseScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Today Review Phase") {
            Scenario("Loading", layout: .fill) {
                AppThemeContainer {
                    TodayReviewPhaseView(phase: .loading, onClose: {})
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Empty", layout: .fill) {
                AppThemeContainer {
                    TodayReviewPhaseView(phase: .empty, onClose: {})
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Failure", layout: .fill) {
                AppThemeContainer {
                    TodayReviewPhaseView(phase: .failure(retry: {}), onClose: {})
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Session · single card", layout: .fill) {
                TodayReviewPhaseSessionScene(fixture: .single)
            }

            Scenario("Session · multi card", layout: .fill) {
                TodayReviewPhaseSessionScene(fixture: .multi)
            }

            // Long-content layout stress (migrated from the former "Today Review
            // Container" surface): one card with very long context + explanation
            // proves the review card stays readable + scrollable under heavy text.
            Scenario("Session · long content stress", layout: .fill) {
                TodayReviewPhaseSessionScene(fixture: .longContent)
            }
        }
    }
}

// MARK: - Fixtures

private enum TodayReviewPhaseFixture {
    case single
    case multi
    case longContent

    var reviewDeckID: UIWorldReviewDeckFixtureID {
        switch self {
        case .single:
            return .phaseSingle
        case .multi:
            return .phaseMulti
        case .longContent:
            return .phaseLongContent
        }
    }

    var expectedEntryCount: Int {
        switch self {
        case .single, .longContent:
            return 1
        case .multi:
            return 3
        }
    }
}

// MARK: - Scene harness

/// `.session` renders `TodayReviewView`, which consumes SwiftData through
/// `@Query`; each scene supplies a manifest-backed in-memory container so the
/// catalog renders without a live store.
private struct TodayReviewPhaseSessionScene: View {
    private let container: ModelContainer
    private let entries: [VocabularyEntry]
    private let currentUserID: String

    init(fixture: TodayReviewPhaseFixture) {
        let reviewSeed = FixtureDatasetStore.requireReviewDeckSeed(for: fixture.reviewDeckID)
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        guard authSeed.isLoggedIn, let userID = authSeed.userId else {
            preconditionFailure("UI World auth.signedIn must declare a logged-in user for TodayReviewPhaseScenarios")
        }
        do {
            let container = try ModelContainer(
                for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let entries = try UITestFixtureSeed.insertReviewDeckSeed(reviewSeed, into: container.mainContext)
            precondition(
                entries.count == fixture.expectedEntryCount,
                "UI World reviewDeck.\(fixture.reviewDeckID.rawValue) expected \(fixture.expectedEntryCount) entries, got \(entries.count)"
            )
            self.container = container
            self.entries = entries
            self.currentUserID = userID
        } catch {
            preconditionFailure("Failed to materialize UI World reviewDeck.\(fixture.reviewDeckID.rawValue) for TodayReviewPhaseScenarios: \(error)")
        }
    }

    var body: some View {
        AppThemeContainer {
            TodayReviewPhaseView(
                phase: .session(
                    entries: entries,
                    allEntries: entries,
                    currentUserID: currentUserID
                ),
                onClose: {}
            )
            .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
