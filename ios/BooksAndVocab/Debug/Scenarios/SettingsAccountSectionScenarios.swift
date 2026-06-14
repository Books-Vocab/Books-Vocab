#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Settings account surface:
/// `SettingsAccountSection`, `SettingsAuthSummary`.
///
/// `SettingsAccountSection` consumes plain value state (`SettingsPresenterState.AuthSection`
/// + optional `SubscriptionSection`) plus a `SettingsPresenterActions` closure bag, so no
/// `AuthManaging` mock or `@MainActor` view-model construction is required — UI World
/// `settings.*` seeds and the existing `noopActions` cover every variant synchronously.
enum SettingsAccountSectionScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Full account section (logged-in / logged-out variants)
        playbook.addScenarios(of: "Account Section · Section") {
            Scenario("Logged Out", layout: .fill) {
                AccountSectionScene(fixtureID: .loggedOut)
            }
            Scenario("Subscribed · Pro Active", layout: .fill) {
                AccountSectionScene(fixtureID: .subscribedActive)
            }
            Scenario("Subscription Loading", layout: .fill) {
                AccountSectionScene(fixtureID: .subscriptionLoading)
            }
            Scenario("Pricing Unavailable · Upgrade CTA", layout: .fill) {
                AccountSectionScene(fixtureID: .pricingUnavailable)
            }
            Scenario("Logged Out · Auth Error", layout: .fill) {
                AccountSectionScene(fixtureID: .accountLoggedOutError)
            }
        }

        // MARK: Auth summary row in isolation
        playbook.addScenarios(of: "Account Section · Auth Summary") {
            Scenario("Initials · Pro", layout: .fill) {
                AuthSummaryScene(fixtureID: .subscribedActive)
            }
            Scenario("Initials · Free", layout: .fill) {
                AuthSummaryScene(fixtureID: .subscriptionFree)
            }
            Scenario("Long Name + Email Overflow", layout: .fill) {
                AuthSummaryScene(fixtureID: .accountLongIdentity)
            }
        }
    }
}

// MARK: - Scene harnesses

private struct AccountSectionScene: View {
    let fixtureID: SettingsFixtureID

    private var state: SettingsPresenterState {
        SettingsFixtures.state(for: fixtureID)
    }

    var body: some View {
        AppThemeContainer {
            ScrollView {
                SettingsAccountSection(
                    state: state.auth,
                    subscription: state.subscription,
                    manualLoginUserId: nil,
                    actions: SettingsPresenterPreviewData.noopActions,
                    onShowAccountDetail: {},
                    onShowSubscriptionDetail: {}
                )
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct AuthSummaryScene: View {
    let fixtureID: SettingsFixtureID

    private var state: SettingsPresenterState {
        SettingsFixtures.state(for: fixtureID)
    }

    var body: some View {
        AppThemeContainer {
            SettingsAuthSummary(
                state: state.auth,
                isProActive: state.subscription?.isActive == true
            )
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
