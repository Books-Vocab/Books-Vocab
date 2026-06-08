#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Settings account surface:
/// `SettingsAccountSection`, `SettingsAuthSummary`.
///
/// `SettingsAccountSection` consumes plain value state (`SettingsPresenterState.AuthSection`
/// + optional `SubscriptionSection`) plus a `SettingsPresenterActions` closure bag, so no
/// `AuthManaging` mock or `@MainActor` view-model construction is required — fixtures from
/// `SettingsFixtures` and the existing `noopActions` cover every variant synchronously.
enum SettingsAccountSectionScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Full account section (logged-in / logged-out variants)
        playbook.addScenarios(of: "Account Section · Section") {
            Scenario("Logged Out", layout: .fill) {
                AccountSectionScene(
                    state: SettingsFixtures.state(for: .loggedOut).auth,
                    subscription: nil
                )
            }
            Scenario("Subscribed · Pro Active", layout: .fill) {
                let full = SettingsFixtures.state(for: .subscribedActive)
                return AccountSectionScene(state: full.auth, subscription: full.subscription)
            }
            Scenario("Subscription Loading", layout: .fill) {
                let full = SettingsFixtures.state(for: .subscriptionLoading)
                return AccountSectionScene(state: full.auth, subscription: full.subscription)
            }
            Scenario("Pricing Unavailable · Upgrade CTA", layout: .fill) {
                let full = SettingsFixtures.state(for: .pricingUnavailable)
                return AccountSectionScene(state: full.auth, subscription: full.subscription)
            }
            Scenario("Logged Out · Auth Error", layout: .fill) {
                AccountSectionScene(
                    state: SettingsAccountSectionScenarios.loggedOutWithError,
                    subscription: nil
                )
            }
        }

        // MARK: Auth summary row in isolation
        playbook.addScenarios(of: "Account Section · Auth Summary") {
            Scenario("Initials · Pro", layout: .fill) {
                AuthSummaryScene(
                    state: SettingsFixtures.state(for: .subscribedActive).auth,
                    isProActive: true
                )
            }
            Scenario("Initials · Free", layout: .fill) {
                AuthSummaryScene(
                    state: SettingsFixtures.state(for: .subscribedActive).auth,
                    isProActive: false
                )
            }
            Scenario("Long Name + Email Overflow", layout: .fill) {
                AuthSummaryScene(
                    state: SettingsAccountSectionScenarios.longIdentityState,
                    isProActive: true
                )
            }
        }
    }

    // MARK: - Synthetic fixtures

    /// Logged-out state carrying a recoverable auth error (no fixture covers this branch).
    static var loggedOutWithError: SettingsPresenterState.AuthSection {
        let base = SettingsFixtures.state(for: .loggedOut).auth
        return .init(
            isLoggedIn: false,
            userInitials: base.userInitials,
            avatarURL: base.avatarURL,
            displayName: base.displayName,
            email: base.email,
            authError: "無法連線至驗證伺服器，請稍後再試。",
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        )
    }

    /// Long display name + email to exercise truncation in the summary row.
    static var longIdentityState: SettingsPresenterState.AuthSection {
        .init(
            isLoggedIn: true,
            userInitials: "麥",
            avatarURL: nil,
            displayName: "麥克斯韋爾・亞歷山大・陳良宇",
            email: "an.extraordinarily.long.email.address@knowledge-graph.example.com",
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        )
    }
}

// MARK: - Scene harnesses

private struct AccountSectionScene: View {
    let state: SettingsPresenterState.AuthSection
    let subscription: SettingsPresenterState.SubscriptionSection?

    var body: some View {
        AppThemeContainer {
            ScrollView {
                SettingsAccountSection(
                    state: state,
                    subscription: subscription,
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
    let state: SettingsPresenterState.AuthSection
    let isProActive: Bool

    var body: some View {
        AppThemeContainer {
            SettingsAuthSummary(state: state, isProActive: isProActive)
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
