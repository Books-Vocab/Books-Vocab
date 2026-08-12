#if DEBUG && canImport(Playbook) && targetEnvironment(simulator)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `ExploreView` surface.
///
/// `ExploreView` is `@Query<SharedDeck>`-backed and normally runs a network
/// auto-sync `.task`. `CatalogTaskPolicy.disabled` skips that task so the view
/// renders purely from the UI World materialized through the production
/// SharedDeckSummary -> SharedDeck projection. Auth comes from UI World auth.signedIn.
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

    var fixtureID: UIWorldExploreFixtureID {
        switch self {
        case .loading: return .loading
        case .populated: return .loaded
        case .empty: return .empty
        case .retry: return .retry
        }
    }

    var preview: ExploreCatalogPreview {
        ExploreCatalogPreview(fixtureID: fixtureID)
    }
}

private struct ExploreScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let preview: ExploreCatalogPreview?

    init(fixture: ExploreFixture) {
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        self.container = ExploreFixtureMaterializer.makeContainer(for: fixture.fixtureID)
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
