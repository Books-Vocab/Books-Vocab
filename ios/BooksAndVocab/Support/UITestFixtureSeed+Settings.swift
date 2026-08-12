#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedSettings(_ id: String, into container: ModelContainer) {
        switch id {
        case "cleanPreferences":
            seedCleanPreferences()
        case SettingsFixtureID.syncTerminalErrorRetrySuccess.rawValue:
            FixtureDatasetStore.activateSettingsFixture(.syncTerminalErrorRetrySuccess)
            AppLog.app.info("UI-test fixture selected: settings.\(id, privacy: .public)")
        case "longContent":
            seedLongContent()
        case "resetLifecycle":
            seedResetLifecycle(into: container)
        default:
            failFixtureSeed("Unknown settings fixture ID: \(id)")
        }
    }

    /// Deterministic preferences baseline for the Settings flow UI test:
    /// review settings reset to `.default` (relaxed mode, review clock running)
    /// and the translation pair pinned to en → zh-Hant. Goes through the
    /// production stores' real write paths (UserDefaults + iCloud KVS layers,
    /// LWW timestamps included) so each launch starts from the same state no
    /// matter what a previous run left behind in the simulator.
    ///
    /// App language is intentionally NOT pinned here: the UI suite already assumes a
    /// zh-Hant simulator (see `AppPage` tab labels). (Until APP-20260806-498c25 there
    /// was a harder reason — `setLanguage` called `Tips.resetDatastore()` inline, which
    /// traps when TipKit is not yet configured, and we run during `App.init`. It now
    /// only records a deferred-reset flag, so that trap is gone.)
    @MainActor
    private static func seedCleanPreferences() {
        // 模擬器限定：這條走 production store 真實寫入路徑（UserDefaults +
        // iCloud KVS + LWW 時間戳），in-memory 容器 guard 罩不到。真機上執行
        // = 覆寫使用者真實複習設定/翻譯語言並跨裝置傳播（與 2026-06-10
        // SwiftData wipe 事故同類、不同儲存平面），一律拒絕。
        #if targetEnvironment(simulator)
        ReviewSettingsStore.shared.update(.default)
        TranslationLanguage.currentSource = .en
        TranslationLanguage.currentTarget = .zhHant
        AppLog.app.info("UI-test fixture seeded: settings.cleanPreferences")
        #else
        failFixtureSeed("UITestFixtureSeed: refused settings.cleanPreferences on device — it writes real UserDefaults/iCloud KVS")
        #endif
    }

    @MainActor
    private static func seedLongContent() {
        #if targetEnvironment(simulator)
        seedSignedInLoginFromWorld(using: .longIdentity)
        AppLog.app.info("UI-test fixture seeded: settings.longContent")
        #else
        failFixtureSeed("UITestFixtureSeed: refused settings.longContent on device — it writes the real Keychain session")
        #endif
    }

    /// Counterexample fixture for the production reset boundary. It starts with
    /// deterministic local cards plus non-default Settings-owned preferences;
    /// the reset action then has observable before/after state to render.
    @MainActor
    private static func seedResetLifecycle(into container: ModelContainer) {
        #if targetEnvironment(simulator)
        if ProcessInfo.processInfo.environment["KG_UI_TEST_SETTINGS_RESET_FAIL_ONCE"] == "1" {
            UserDefaults.standard.removeObject(forKey: "kg.ui.test.settings.reset.failure.consumed")
        }
        seedSignedInLoginFromWorld(using: .settingsSignedIn)

        ReviewSettingsStore.shared.update(
            ReviewSettings(
                mode: .intensive,
                customInitialIntervalHours: 12,
                customRememberedMultiplier: 1.9,
                customForgotMultiplier: 0.45,
                customMinimumIntervalHours: 6,
                customMaximumIntervalHours: 1440,
                autoplaySpeed: .fast,
                autoplaySoundEnabled: true
            )
        )
        TranslationLanguage.restore(
            source: .en,
            sourceUpdatedAt: 1_735_000_000,
            target: .ja,
            targetUpdatedAt: 1_735_000_000
        )
        AppLanguageStore.shared.setLanguage(.system)
        AppAppearanceStore.shared.setAppearance(.dark)
        AutoSyncSettingsStore.shared.setEnabled(true)
        AutoLinkSettingsStore.shared.setEnabled(false, updatedAt: 1_735_000_000)
        FeedbackSettingsStore.shared.setSoundFeedbackEnabled(true)
        FeedbackSettingsStore.shared.setHapticFeedbackEnabled(false)

        let context = ModelContext(container)
        do {
            try clearVocabularyEntries(from: context)
            let fixedDate = Date(timeIntervalSince1970: 1_735_000_000)
            for (word, translation, contextText) in [
                ("boundary", "邊界", "reset fixture card one"),
                ("observable", "可觀察", "reset fixture card two"),
                ("terminal", "終端", "reset fixture card three"),
            ] {
                let entry = VocabularyEntry(
                    word: word,
                    translation: translation,
                    context: contextText,
                    bookTitle: "Settings reset fixture"
                )
                entry.syncStatus = VocabularySyncState.synced.rawValue
                entry.actionType = VocabularySyncAction.add.rawValue
                entry.isArchived = false
                entry.dateAdded = fixedDate
                entry.nextReviewAt = fixedDate
                context.insert(entry)
            }
            try context.save()
        } catch {
            failFixtureSeed("UITestFixtureSeed: settings.resetLifecycle could not seed local cards: \(error.localizedDescription)")
        }
        AppLog.app.info("UI-test fixture seeded: settings.resetLifecycle")
        #else
        failFixtureSeed("UITestFixtureSeed: refused settings.resetLifecycle on device — it writes real UserDefaults/iCloud KVS")
        #endif
    }
}
#endif
