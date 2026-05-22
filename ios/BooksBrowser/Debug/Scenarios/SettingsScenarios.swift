#if DEBUG
import Playbook
import SwiftUI

/// Catalog scenarios for the Settings surface.
/// Reuses `SettingsPresenterPreviewData` (defined in `SettingsPresenter+Preview.swift`)
/// so state stays in lock-step with the existing `#Preview` blocks.
enum SettingsScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings") {
            Scenario("Logged Out", layout: .fill) {
                scene(state: SettingsPresenterPreviewData.loggedOut)
            }
            Scenario("Subscribed Active", layout: .fill) {
                scene(state: SettingsPresenterPreviewData.subscribedActive)
            }
            Scenario("Subscription Loading", layout: .fill) {
                scene(state: SettingsPresenterPreviewData.subscriptionLoading)
            }
            Scenario("Deleting Account", layout: .fill) {
                scene(state: SettingsPresenterPreviewData.deletingAccount)
            }
            Scenario("Pricing Unavailable", layout: .fill) {
                scene(state: SettingsPresenterPreviewData.pricingUnavailable)
            }
            Scenario("Debug Backend Local", layout: .fill) {
                scene(
                    state: SettingsPresenterPreviewData.debugBackendLocal,
                    manualUserId: "debug-user-id",
                    localURL: "http://127.0.0.1:8000"
                )
            }
        }
    }

    private static func scene(
        state: SettingsPresenterState,
        manualUserId: String? = nil,
        localURL: String? = nil
    ) -> some View {
        AppThemeContainer {
            NavigationStack {
                SettingsPresenter(
                    state: state,
                    translationSourceLang: .constant(.en),
                    translationTargetLang: .constant(.zhHant),
                    onTranslationLanguageChanged: { _, _ in true },
                    manualLoginUserId: manualUserId.map { .constant($0) },
                    debugLocalServerURL: localURL.map { .constant($0) },
                    actions: SettingsPresenterPreviewData.noopActions
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
