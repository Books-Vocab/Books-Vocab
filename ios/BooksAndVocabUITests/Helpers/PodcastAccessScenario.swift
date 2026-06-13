import XCTest

/// Podcast access state matrix for UI tests.
///
/// Data fixtures and access state are intentionally separate:
/// `kg.fixture.dataset.v1` controls render data, while these launch fixtures
/// control auth token and Pro entitlement state.
enum PodcastAccessScenario: String, CaseIterable {
    case guest
    case free
    case pro

    var fixtures: [UITestFixture] {
        switch self {
        case .guest:
            return [.authTieredCatalog]
        case .free:
            return [.authTieredCatalog, .authSignedIn]
        case .pro:
            return [.authTieredCatalog, .authSignedIn, .entitlementsProAccess]
        }
    }

    var environment: [String: String] {
        PodcastFixture.tieredCatalogEnvironment
    }

    var perfLog: String {
        "podcast-access-\(rawValue)"
    }
}

extension UITestCase {
    @discardableResult
    func launchPodcastAccessScenario(_ scenario: PodcastAccessScenario) -> XCUIApplication {
        launchIsolatedApp(
            fixtures: scenario.fixtures,
            extraEnvironment: scenario.environment,
            perfLog: scenario.perfLog
        )
    }
}
