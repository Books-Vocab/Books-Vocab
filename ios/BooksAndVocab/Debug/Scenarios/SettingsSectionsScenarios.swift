#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the higher-level Settings section blocks:
/// `SettingsReviewSection` (full 複習節奏 screen) and `SettingsPreferencesSection`
/// (偏好 card). Preferences state is sourced from UI World `settings.*` seeds so
/// Catalog, UITest, and demo datasets share the same user-state owner.
///
/// `SettingsReviewSection` reads `\.reviewSettingsStore`; we inject an isolated
/// `ReviewSettingsStore(previewSettings:)` per scenario from inside a View body
/// scene so any actor isolation on store init is honoured.
enum SettingsSectionsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Review Section (複習節奏)
        playbook.addScenarios(of: "Settings Sections · Review") {
            Scenario("寬鬆模式", layout: .fill) {
                ReviewSectionScene(settings: ReviewSettings(
                    mode: .relaxed,
                    customInitialIntervalHours: 12,
                    customRememberedMultiplier: 1.9,
                    customForgotMultiplier: 0.45,
                    customMinimumIntervalHours: 6,
                    customMaximumIntervalHours: 1440
                ))
            }
            Scenario("密集模式", layout: .fill) {
                ReviewSectionScene(settings: ReviewSettings(
                    mode: .intensive,
                    customInitialIntervalHours: 12,
                    customRememberedMultiplier: 1.9,
                    customForgotMultiplier: 0.45,
                    customMinimumIntervalHours: 6,
                    customMaximumIntervalHours: 1440
                ))
            }
            Scenario("自訂模式 / 展開參數", layout: .fill) {
                ReviewSectionScene(settings: ReviewSettings(
                    mode: .custom,
                    customInitialIntervalHours: 24,
                    customRememberedMultiplier: 2.1,
                    customForgotMultiplier: 0.35,
                    customMinimumIntervalHours: 4,
                    customMaximumIntervalHours: 2160
                ))
            }
            Scenario("已凍結進度", layout: .fill) {
                ReviewSectionScene(settings: ReviewSettings(
                    mode: .relaxed,
                    customInitialIntervalHours: 12,
                    customRememberedMultiplier: 1.9,
                    customForgotMultiplier: 0.45,
                    customMinimumIntervalHours: 6,
                    customMaximumIntervalHours: 1440,
                    isProgressPaused: true,
                    progressPausedAt: Date(timeIntervalSince1970: 1_733_500_000)
                ))
            }
        }

        // MARK: Preferences Section (偏好)
        playbook.addScenarios(of: "Settings Sections · Preferences") {
            Scenario("含自動同步", layout: .fill) {
                PreferencesSectionScene(fixtureID: .subscribedActive)
            }
            Scenario("自動同步關閉", layout: .fill) {
                PreferencesSectionScene(fixtureID: .preferencesAutoSyncOff)
            }
            Scenario("未登入 / 無同步列", layout: .fill) {
                PreferencesSectionScene(fixtureID: .preferencesLoggedOutNoSync)
            }
        }
    }
}

// MARK: - Scene harnesses

/// Body is main-actor isolated, so the `ReviewSettingsStore` init runs in a
/// safe context regardless of its isolation.
private struct ReviewSectionScene: View {
    let settings: ReviewSettings

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                SettingsReviewSection()
            }
        }
        .environment(\.reviewSettingsStore, ReviewSettingsStore(previewSettings: settings))
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct PreferencesSectionScene: View {
    let fixtureID: SettingsFixtureID

    private var state: SettingsPresenterState.PreferencesSection {
        SettingsFixtures.state(for: fixtureID).preferences
    }

    var body: some View {
        AppThemeContainer {
            ScrollView {
                SettingsPreferencesSection(
                    state: state,
                    actions: Self.noopActions,
                    onShowTranslationLanguage: {},
                    onShowReviewSettings: {}
                )
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static let noopActions = SettingsPresenterActions(
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
}
#endif
