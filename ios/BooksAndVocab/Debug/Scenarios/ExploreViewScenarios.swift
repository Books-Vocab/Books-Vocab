#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `ExploreView` surface.
///
/// `ExploreView` is `@Query<SharedDeck>`-backed and normally runs a network
/// auto-sync `.task`. `CatalogTaskPolicy.disabled` skips that task so the view
/// renders purely off the locally-seeded in-memory store
/// (`SharedDeckCatalogFixtures`). Auth comes from UI World `auth.signedIn`.
enum ExploreViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Explore View") {
            Scenario("Content / Populated", layout: .fill) {
                ExploreScene(fixture: .populated)
            }
            Scenario("Empty", layout: .fill) {
                ExploreScene(fixture: .empty)
            }
        }
    }
}

private enum ExploreFixture {
    case populated
    case empty

    var specs: [SharedDeckCatalogFixtures.DeckSpec] {
        switch self {
        case .populated: return SharedDeckCatalogFixtures.populated
        case .empty: return []
        }
    }
}

private struct ExploreScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth

    init(fixture: ExploreFixture) {
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        self.container = SharedDeckCatalogFixtures.makeContainer(specs: fixture.specs)
        self.auth = Self.makeAuth(from: authSeed)
    }

    var body: some View {
        AppThemeContainer {
            ExploreView()
                .modelContainer(container)
                .environment(\.authManager, auth)
                .environment(\.catalogTaskPolicy, .disabled)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        guard seed.isLoggedIn else {
            preconditionFailure("UI World auth.signedIn must be logged in for ExploreViewScenarios")
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
