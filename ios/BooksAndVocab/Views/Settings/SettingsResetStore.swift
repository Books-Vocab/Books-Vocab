import Foundation
import SwiftData

/// Boundary for the state that the Settings reset lifecycle renders.
///
/// The reset service owns cleanup mutations, while this port owns observing
/// the stores that prove what was left before and after that mutation. Keeping
/// the two seams separate lets unit tests model partial cleanup without
/// replacing SwiftData or UserDefaults with presentation constants.
@MainActor
protocol SettingsResetStorePort: AnyObject {
    func readSnapshot(
        authManager: any AuthManaging,
        modelContext: ModelContext
    ) -> SettingsResetLifecycle.Snapshot
    func resetPreferences()
}

@MainActor
final class LiveSettingsResetStore: SettingsResetStorePort {
    func readSnapshot(
        authManager: any AuthManaging,
        modelContext: ModelContext
    ) -> SettingsResetLifecycle.Snapshot {
        do {
            let descriptor = FetchDescriptor<VocabularyEntry>(predicate: #Predicate {
                $0.syncStatus == 1 &&
                $0.actionType != "delete" &&
                $0.isArchived == false
            })
            let localCardCount = try modelContext.fetch(descriptor).count
            return .init(
                localCardCount: localCardCount,
                hasCustomPreferences: hasCustomPreferences,
                isLoggedIn: authManager.isLoggedIn
            )
        } catch {
            AppLog.kg.error("Settings reset snapshot could not read local cards: \(error.localizedDescription)")
            return .init(
                unreadableLocalCardCount: error.localizedDescription,
                hasCustomPreferences: hasCustomPreferences,
                isLoggedIn: authManager.isLoggedIn
            )
        }
    }

    func resetPreferences() {
        ReviewSettingsStore.shared.update(.default)
        TranslationLanguage.currentSource = .en
        TranslationLanguage.currentTarget = .zhHant
        // A root language refresh would destroy the active Settings
        // navigation before the terminal reset state can be observed.
        AppLanguageStore.shared.setLanguage(.system, preservingRootPresentation: true)
        AppAppearanceStore.shared.setAppearance(.system)
        AutoSyncSettingsStore.shared.setEnabled(false)
        AutoLinkSettingsStore.shared.setEnabled(true)
        FeedbackSettingsStore.shared.setSoundFeedbackEnabled(false)
        FeedbackSettingsStore.shared.setHapticFeedbackEnabled(true)
    }

    private var hasCustomPreferences: Bool {
        let review = ReviewSettingsStore.shared.settings
        let defaults = ReviewSettings.default
        return AppLanguageStore.shared.selection != .system
            || AppAppearanceStore.shared.selection != .system
            || TranslationLanguage.currentSource != .en
            || TranslationLanguage.currentTarget != .zhHant
            || review.mode != defaults.mode
            || review.customInitialIntervalHours != defaults.customInitialIntervalHours
            || review.customRememberedMultiplier != defaults.customRememberedMultiplier
            || review.customForgotMultiplier != defaults.customForgotMultiplier
            || review.customMinimumIntervalHours != defaults.customMinimumIntervalHours
            || review.customMaximumIntervalHours != defaults.customMaximumIntervalHours
            || review.isProgressPaused != defaults.isProgressPaused
            || review.autoplaySpeed != defaults.autoplaySpeed
            || review.autoplaySoundEnabled != defaults.autoplaySoundEnabled
            || AutoSyncSettingsStore.shared.isEnabled
            || !AutoLinkSettingsStore.shared.isEnabled
            || FeedbackSettingsStore.shared.soundFeedbackEnabled
            || !FeedbackSettingsStore.shared.hapticFeedbackEnabled
    }
}
