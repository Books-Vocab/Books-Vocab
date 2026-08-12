#if os(iOS) && DEBUG && targetEnvironment(simulator)
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedExplore(_ id: String, into container: ModelContainer) {
        let fixtureID: UIWorldExploreFixtureID
        if id == "partial" {
            // Partial is an explicit debug alias: the service starts with a
            // loaded cache, then returns a real list failure.
            fixtureID = .retry
        } else if let parsed = UIWorldExploreFixtureID(rawValue: id) {
            fixtureID = parsed
        } else {
            failFixtureSeed("Unknown explore fixture ID: \(id)")
        }
        _ = container
        ExploreFixtureMaterializer.prepare(fixtureID)
    }
}
#endif
