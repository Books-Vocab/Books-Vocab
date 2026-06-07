#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Today Review surface.
///
/// `TodayReviewView` itself is driven by a live `TodayReviewState` (SwiftData
/// container + reviewSettings/auth/kgService environment) with no injectable
/// state seam, so the full view is not catalogued directly. Instead we render
/// its presenter via the internal `TodayReviewFixtureScene`, which is the same
/// seam the production `#Preview`s use — it already wraps `AppThemeContainer`
/// and injects `AppAppearanceStore.preview`. Each `TodayReviewFixtureID`
/// covers a meaningful card state.
enum TodayReviewViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Today Review View") {
            Scenario("Front (question)", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .front)
            }
            Scenario("Back (answer revealed)", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .back)
            }
            Scenario("Autoplay", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .autoplay)
            }
            Scenario("Completed (queue empty)", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .completed)
            }
        }
    }
}
#endif
