#if DEBUG && canImport(Playbook) && targetEnvironment(simulator)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `ExploreView` surface.
///
/// `ExploreView` is `@Query<SharedDeck>`-backed and normally runs a network
/// auto-sync task. A live named async service fake drives each state; the
/// The successful path materializes through the production
/// SharedDeckSummary -> SharedDeck projection. Auth comes from
/// UI World auth.signedIn.
@MainActor
enum ExploreViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Explore View") {
            Scenario("Loading", layout: .fill) {
                MainActor.assumeIsolated { ExploreScene(fixture: .loading) }
            }
            Scenario("Content / Populated", layout: .fill) {
                MainActor.assumeIsolated { ExploreScene(fixture: .populated) }
            }
            Scenario("Empty", layout: .fill) {
                MainActor.assumeIsolated { ExploreScene(fixture: .empty) }
            }
            Scenario("Error / Retry", layout: .fill) {
                MainActor.assumeIsolated { ExploreScene(fixture: .retry) }
            }
            Scenario("Partial / Stale Cache", layout: .fill) {
                MainActor.assumeIsolated { ExploreScene(fixture: .partial) }
            }
        }
    }
}

@MainActor
private enum ExploreFixture: Equatable {
    case loading
    case populated
    case empty
    case retry
    case partial

    var fixtureID: UIWorldExploreFixtureID {
        switch self {
        case .loading: return .loading
        case .populated: return .loaded
        case .empty: return .empty
        case .retry: return .retry
        case .partial: return .retry
        }
    }

    var preview: ExploreCatalogPreview {
        ExploreCatalogPreview(
            fixtureID: fixtureID,
            initialCacheFixtureID: self == .partial ? .loaded : nil
        )
    }

    var service: ExploreUIWorldCatalogService {
        ExploreUIWorldCatalogService(
            fixtureID: fixtureID,
            initialCacheFixtureID: self == .partial ? .loaded : nil
        )
    }
}

@MainActor
private struct ExploreScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let preview: ExploreCatalogPreview?
    let service: ExploreUIWorldCatalogService

    init(fixture: ExploreFixture) {
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        self.container = ExploreFixtureMaterializer.makeContainer(
            for: fixture.fixtureID,
            seedCatalog: false
        )
        self.auth = Self.makeAuth(from: authSeed)
        self.preview = fixture.preview
        self.service = fixture.service
    }

    var body: some View {
        AppThemeContainer {
            ExploreView(catalogPreview: preview, catalogService: service)
                .modelContainer(container)
                .environment(\.authManager, auth)
                .environment(\.catalogTaskPolicy, .live)
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
