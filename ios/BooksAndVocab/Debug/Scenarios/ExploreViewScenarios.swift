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
            Scenario("Loading", layout: .fill) {
                ExploreScene(fixture: .loading)
            }
            Scenario("Content / Populated", layout: .fill) {
                ExploreScene(fixture: .populated)
            }
            Scenario("Empty", layout: .fill) {
                ExploreScene(fixture: .empty)
            }
            Scenario("Error / Retry", layout: .fill) {
                ExploreScene(fixture: .retry)
            }
        }
    }
}

private enum ExploreFixture {
    case loading
    case populated
    case empty
    case retry

    var specs: [SharedDeckCatalogFixtures.DeckSpec] {
        switch self {
        case .loading, .retry: return SharedDeckCatalogFixtures.populated
        case .populated: return SharedDeckCatalogFixtures.populated
        case .empty: return []
        }
    }

    var preview: ExploreCatalogPreview? {
        switch self {
        case .loading:
            return .init(initialPhase: .loading, retryPhase: .loaded)
        case .retry:
            return .init(initialPhase: .error, retryPhase: .loaded)
        case .populated, .empty:
            return nil
        }
    }
}

private struct ExploreScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let preview: ExploreCatalogPreview?

    init(fixture: ExploreFixture) {
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        self.container = SharedDeckCatalogFixtures.makeContainer(specs: fixture.specs)
        self.auth = Self.makeAuth(from: authSeed)
        self.preview = fixture.preview
    }

    var body: some View {
        AppThemeContainer {
            ExploreView(catalogPreview: preview)
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
