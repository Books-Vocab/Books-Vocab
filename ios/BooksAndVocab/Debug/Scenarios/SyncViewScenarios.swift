#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `SyncView` surface (待同步單字審閱).
///
/// `SyncView` is `@Query`-backed over `VocabularyEntry` (`syncStatus != 1`, i.e.
/// not yet synced) and renders `SyncPresenter(state:)`. Its `.task` only calls
/// `refreshStepLayoutIfIdle()` — pure local layout, no network — so the view is
/// fully catalogable by seeding a fresh in-memory store. `presenterState` reads
/// `authManager.isLoggedIn` / `kgService.isConnected`; auth and pending row
/// state both come from UI World, so missing sync/auth seeds or SwiftData save
/// failure fail at catalog construction time.
enum SyncViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Sync View") {
            Scenario("Pending · adds + deletes", layout: .fill) {
                SyncViewScene(fixture: .mixed, expected: .mixed)
            }
            Scenario("Pending · single add", layout: .fill) {
                SyncViewScene(fixture: .single, expected: .singleAdd)
            }
            Scenario("Empty · nothing pending", layout: .fill) {
                SyncViewScene(fixture: .empty, expected: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum SyncViewFixture {
    case mixed
    case single
    case empty

    var vocabularyID: UIWorldVocabularyFixtureID {
        switch self {
        case .mixed:
            return .syncPendingMixed
        case .single:
            return .syncPendingSingle
        case .empty:
            return .syncEmpty
        }
    }
}

private enum SyncViewExpectedShape {
    case mixed
    case singleAdd
    case empty
}

// MARK: - Scene harness

private struct SyncViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth

    init(fixture: SyncViewFixture, expected: SyncViewExpectedShape) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .guest)
        do {
            let container = try ModelContainer(
                for: VocabularyEntry.self, Notebook.self, ReviewRecord.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let entries = try MainActor.assumeIsolated {
                try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)
            }
            Self.validate(entries, fixture: fixture, expected: expected)
            self.container = container
            self.auth = Self.makeAuth(from: authSeed)
        } catch {
            preconditionFailure("Failed to materialize UI World vocabulary.\(fixture.vocabularyID.rawValue) for SyncViewScenarios: \(error)")
        }
    }

    var body: some View {
        AppThemeContainer {
            SyncView()
                .modelContainer(container)
                .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static func validate(
        _ entries: [VocabularyEntry],
        fixture: SyncViewFixture,
        expected: SyncViewExpectedShape
    ) {
        let pending = entries.filter { $0.syncStatus != VocabularySyncState.synced.rawValue }
        let actions = pending.map(\.actionType)
        switch expected {
        case .mixed:
            guard pending.count > 1,
                  actions.contains(VocabularySyncAction.add.rawValue),
                  actions.contains(VocabularySyncAction.delete.rawValue) else {
                preconditionFailure("UI World vocabulary.\(fixture.vocabularyID.rawValue) must declare multiple pending add/delete rows")
            }
        case .singleAdd:
            guard pending.count == 1, actions == [VocabularySyncAction.add.rawValue] else {
                preconditionFailure("UI World vocabulary.\(fixture.vocabularyID.rawValue) must declare one pending add row")
            }
        case .empty:
            guard pending.isEmpty else {
                preconditionFailure("UI World vocabulary.\(fixture.vocabularyID.rawValue) must declare no pending rows")
            }
        }
    }

    private static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        guard !seed.isLoggedIn else {
            preconditionFailure("UI World auth.guest must be logged out for SyncViewScenarios")
        }
        return CatalogPreviewAuth(
            isLoggedIn: seed.isLoggedIn,
            userId: seed.userId,
            token: seed.token,
            displayName: seed.displayName,
            userEmail: seed.email
        )
    }
}
#endif
