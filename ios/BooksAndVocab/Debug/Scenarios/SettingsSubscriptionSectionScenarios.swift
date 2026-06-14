#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

enum SettingsSubscriptionSectionScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings Subscription Section") {
            Scenario("Pro Active", layout: .fillH) {
                SubscriptionSectionScene(fixtureID: .subscribedActive)
            }

            Scenario("Loading", layout: .fillH) {
                SubscriptionSectionScene(fixtureID: .subscriptionLoading)
            }

            Scenario("Pricing Unavailable", layout: .fillH) {
                SubscriptionSectionScene(fixtureID: .pricingUnavailable)
            }

            Scenario("Inactive · Free", layout: .fillH) {
                SubscriptionSectionScene(fixtureID: .subscriptionFree)
            }
        }
    }
}

private struct SubscriptionSectionScene: View {
    let fixtureID: SettingsFixtureID

    private var state: SettingsPresenterState.SubscriptionSection {
        let fullState = SettingsFixtures.state(for: fixtureID)
        guard let subscription = fullState.subscription else {
            preconditionFailure("UI World settings.\(fixtureID.rawValue) must declare subscription section")
        }
        return subscription
    }

    var body: some View {
        AppThemeContainer {
            ScrollView {
                SettingsSubscriptionSection(
                    state: state,
                    actions: SettingsPresenterPreviewData.noopActions
                )
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
