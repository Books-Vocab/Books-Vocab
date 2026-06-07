import SwiftUI

// MARK: - Preview

enum SettingsPresenterPreviewData {

    static let noopActions = SettingsPresenterActions(
        dismiss: {},
        loginWithGoogle: {},
        loginWithApple: {},
        logout: {},
        manualLogin: {},
        useProductionBackend: {},
        useLocalBackend: {},
        selectLanguage: { _ in },
        selectAppearance: { _ in },
        showSubscriptionPaywall: {},
        requestDeleteAccount: {},

        openPrivacyPolicy: {},
        openTermsOfService: {},
        openSupport: {},
        requestAppRating: {},
        resync: {},
        toggleAutoSync: { _ in },
        exportVocabularyCSV: {}
    )

    static var loggedOut: SettingsPresenterState { SettingsFixtures.state(for: .loggedOut) }
    static var subscribedActive: SettingsPresenterState { SettingsFixtures.state(for: .subscribedActive) }
    static var subscriptionLoading: SettingsPresenterState { SettingsFixtures.state(for: .subscriptionLoading) }
    static var deletingAccount: SettingsPresenterState { SettingsFixtures.state(for: .deletingAccount) }
    static var pricingUnavailable: SettingsPresenterState { SettingsFixtures.state(for: .pricingUnavailable) }
    static var debugBackendLocal: SettingsPresenterState { SettingsFixtures.state(for: .debugBackendLocal) }
}

struct SettingsFixtureScene: View {
    let fixtureID: SettingsFixtureID

    private var renderModel: SettingsFixtureRenderModel {
        SettingsFixtures.renderModel(for: fixtureID)
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                SettingsPresenter(
                    state: renderModel.state,
                    translationSourceLang: .constant(.en),
                    translationTargetLang: .constant(.zhHant),
                    onTranslationLanguageChanged: { _, _ in true },
                    manualLoginUserId: renderModel.manualLoginUserId.map { .constant($0) },
                    debugLocalServerURL: renderModel.debugLocalServerURL.map { .constant($0) },
                    actions: SettingsPresenterPreviewData.noopActions
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

#Preview("Settings / Logged Out") {
    SettingsFixtureScene(fixtureID: .loggedOut)
}

#Preview("Settings / Subscribed Active") {
    SettingsFixtureScene(fixtureID: .subscribedActive)
}

#Preview("Settings / Subscription Loading") {
    SettingsFixtureScene(fixtureID: .subscriptionLoading)
}

#Preview("Settings / Deleting Account") {
    SettingsFixtureScene(fixtureID: .deletingAccount)
}

#Preview("Settings / Pricing Unavailable") {
    SettingsFixtureScene(fixtureID: .pricingUnavailable)
}

#Preview("Settings / Debug Backend Local") {
    SettingsFixtureScene(fixtureID: .debugBackendLocal)
}
