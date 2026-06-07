#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Settings surface.
/// Reuses `SettingsPresenterPreviewData` (defined in `SettingsPresenter+Preview.swift`)
/// so state stays in lock-step with the existing `#Preview` blocks.
enum SettingsScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings") {
            Scenario("Logged Out", layout: .fill) {
                SettingsFixtureScene(fixtureID: .loggedOut)
            }
            Scenario("Subscribed Active", layout: .fill) {
                SettingsFixtureScene(fixtureID: .subscribedActive)
            }
            Scenario("Subscription Loading", layout: .fill) {
                SettingsFixtureScene(fixtureID: .subscriptionLoading)
            }
            Scenario("Deleting Account", layout: .fill) {
                SettingsFixtureScene(fixtureID: .deletingAccount)
            }
            Scenario("Pricing Unavailable", layout: .fill) {
                SettingsFixtureScene(fixtureID: .pricingUnavailable)
            }
            Scenario("Debug Backend Local", layout: .fill) {
                SettingsFixtureScene(fixtureID: .debugBackendLocal)
            }
        }
    }
}
#endif
