#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Today Review surface.
/// Reuses fixture-driven preview scenes so Preview / Catalog / Snapshot stay aligned.
enum TodayReviewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Today Review") {
            Scenario("Front", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .front)
            }
            Scenario("Back", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .back)
            }
            Scenario("Completed", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .completed)
            }
            Scenario("Autoplay", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .autoplay)
            }
            Scenario("Autoplay paused", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .autoplayPaused)
            }
            Scenario("Production · Front", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .productionFront)
            }
            Scenario("Production · Back", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .productionBack)
            }
            Scenario("Long content overflow", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .longContent)
            }
        }
    }
}
#endif
