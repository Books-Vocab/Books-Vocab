#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedSettings(_ id: String, into container: ModelContainer) {
        if id == "cleanPreferences" {
            seedCleanPreferences()
            return
        }

        guard let fixtureID = SettingsFixtureID(rawValue: id) else {
            failFixtureSeed("Unknown settings fixture ID: \(id)")
        }

        switch fixtureID {
        case .syncTerminalErrorRetrySuccess:
            let seed = FixtureDatasetStore.requireSettingsSeed(for: fixtureID)
            // This lifecycle must run as the canonical settings account, not
            // whichever auth fixture happened to precede it on the launch
            // line. In particular, auth.signedIn is the demo account and
            // SettingsCoordinator intentionally refuses sync in demo mode.
            seedSignedInLoginFromWorld(using: authFixtureID(for: seed))
            FixtureDatasetStore.activateSettingsFixture(fixtureID)
            AppLog.app.info("UI-test fixture selected: settings.\(id, privacy: .public)")
        case .longContentCounterexample:
            seedLongContent(from: fixtureID)
        case .resetCounterexample:
            seedResetLifecycle(from: fixtureID, into: container)
        default:
            failFixtureSeed("Settings UI test requires a counterexample fixture, got \(fixtureID.rawValue)")
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
    private static func seedLongContent(from fixtureID: SettingsFixtureID) {
        #if targetEnvironment(simulator)
        let seed = FixtureDatasetStore.requireSettingsSeed(for: fixtureID)
        seedSignedInLoginFromWorld(using: authFixtureID(for: seed))
        applySettingsPreferences(seed.preferences)
        logEvidence(for: fixtureID, seed: seed)
        AppLog.app.info("UI-test fixture seeded: settings.\(fixtureID.rawValue)")
        #else
        failFixtureSeed("UITestFixtureSeed: refused settings.\(fixtureID.rawValue) on device — it writes the real Keychain session")
        #endif
    }

    /// Counterexample fixture for the production reset boundary. It starts with
    /// deterministic local cards plus non-default Settings-owned preferences;
    /// the reset action then has observable before/after state to render.
    @MainActor
    private static func seedResetLifecycle(from fixtureID: SettingsFixtureID, into container: ModelContainer) {
        #if targetEnvironment(simulator)
        if ProcessInfo.processInfo.environment["KG_UI_TEST_SETTINGS_RESET_FAIL_ONCE"] == "1" {
            UserDefaults.standard.removeObject(forKey: "kg.ui.test.settings.reset.failure.consumed")
        }

        let settingsSeed = FixtureDatasetStore.requireSettingsSeed(for: fixtureID)
        guard let lifecycle = settingsSeed.resetLifecycle else {
            failFixtureSeed("UI World settings.\(fixtureID.rawValue) must declare resetLifecycle")
        }
        seedSignedInLoginFromWorld(using: authFixtureID(for: settingsSeed))
        applySettingsPreferences(settingsSeed.preferences)

        // Settings reads reset snapshots from the app environment's main context.
        // Seed through that same context so the reset boundary observes the
        // canonical cards immediately after the fixture save; a separate
        // ModelContext(container) can leave the UI projection at zero on the
        // in-memory UI-test store.
        let context = container.mainContext
        do {
            try clearVocabularyEntries(from: context)
            let vocabularySeed = FixtureDatasetStore.requireVocabularySeed(for: .vocabListPopulated)
            let expectedCount = lifecycle.before.localCardCount
            guard expectedCount > 0, vocabularySeed.entries.count >= expectedCount else {
                failFixtureSeed(
                    "UI World settings.\(fixtureID.rawValue) requires \(expectedCount) canonical vocabulary entries"
                )
            }

            let notebook = Notebook(
                remoteId: vocabularySeed.notebookRemoteId,
                name: vocabularySeed.notebookName
            )
            notebook.syncStatus = vocabularySeed.notebookSyncStatus
            context.insert(notebook)

            for entrySeed in vocabularySeed.entries.prefix(expectedCount) {
                context.insert(makeVocabularyEntry(from: entrySeed, notebookId: vocabularySeed.notebookRemoteId))
            }
            try context.save()
        } catch {
            failFixtureSeed("UITestFixtureSeed: settings.\(fixtureID.rawValue) could not seed canonical local cards: \(error.localizedDescription)")
        }
        logEvidence(for: fixtureID, seed: settingsSeed)
        AppLog.app.info("UI-test fixture seeded: settings.\(fixtureID.rawValue)")
        #else
        failFixtureSeed("UITestFixtureSeed: refused settings.\(fixtureID.rawValue) on device — it writes real UserDefaults/iCloud KVS")
        #endif
    }

    @MainActor
    private static func applySettingsPreferences(_ seed: SettingsFixtureSeed.Preferences) {
        guard let language = AppLanguage.allCases.first(where: { $0.titleKey == seed.selectedLanguage }) else {
            failFixtureSeed("UI World settings preference has unknown language \(seed.selectedLanguage)")
        }
        guard let appearance = AppAppearanceMode.allCases.first(where: { $0.titleKey == seed.selectedAppearance }) else {
            failFixtureSeed("UI World settings preference has unknown appearance \(seed.selectedAppearance)")
        }
        guard let source = TranslationLanguage.allCases.first(where: { $0.nativeName == seed.translationSource }),
              let target = TranslationLanguage.allCases.first(where: { $0.nativeName == seed.translationTarget })
        else {
            failFixtureSeed("UI World settings preference has unknown translation pair")
        }
        guard let mode = ReviewSettingsMode.allCases.first(where: { $0.displayName == seed.selectedReviewMode }) else {
            failFixtureSeed("UI World settings preference has unknown review mode \(seed.selectedReviewMode)")
        }

        AppLanguageStore.shared.setLanguage(language)
        AppAppearanceStore.shared.setAppearance(appearance)
        TranslationLanguage.currentSource = source
        TranslationLanguage.currentTarget = target
        var review = ReviewSettings.default
        review.mode = mode
        ReviewSettingsStore.shared.update(review)
        AutoSyncSettingsStore.shared.setEnabled(seed.autoSyncEnabled)
    }

    private static func authFixtureID(for seed: SettingsFixtureSeed) -> UIWorldAuthFixtureID {
        let prefix = "auth."
        guard seed.authFixtureRef.hasPrefix(prefix),
              let fixtureID = UIWorldAuthFixtureID(rawValue: String(seed.authFixtureRef.dropFirst(prefix.count)))
        else {
            failFixtureSeed("UI World settings.\(seed.authFixtureRef) must reference a known auth fixture")
        }
        return fixtureID
    }

    private static func logEvidence(for fixtureID: SettingsFixtureID, seed: SettingsFixtureSeed) {
        guard let evidence = seed.evidence else {
            failFixtureSeed("UI World settings.\(fixtureID.rawValue) must declare evidence")
        }
        AppLog.app.info("UI-test fixture evidence: fixture=\(fixtureID.rawValue) asset=\(evidence.assetID)")
    }
}
#endif
