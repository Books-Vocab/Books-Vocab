#if os(iOS) && DEBUG && targetEnvironment(simulator)
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedExplore(_ id: String, into container: ModelContainer) {
        guard let fixtureID = UIWorldExploreFixtureID(rawValue: id) else {
            failFixtureSeed("Unknown explore fixture ID: \(id)")
        }
        ExploreFixtureMaterializer.seed(fixtureID, into: container)
    }
}
#endif
