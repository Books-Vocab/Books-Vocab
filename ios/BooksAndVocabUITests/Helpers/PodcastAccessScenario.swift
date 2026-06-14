import XCTest

/// Podcast access state matrix for UI tests.
///
/// Launch fixtures select which state path to seed; UI World v2 remains the
/// SoT for render data, auth token state, and Pro entitlement values.
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
