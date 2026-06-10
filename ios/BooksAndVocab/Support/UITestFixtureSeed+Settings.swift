#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedSettings(_ id: String, into container: ModelContainer) {
        switch id {
        case "cleanPreferences":
            seedCleanPreferences()
        default:
            AppLog.app.warning("Unknown settings fixture ID: \(id)")
        }
    }

    /// Deterministic preferences baseline for the Settings flow UI test:
    /// review settings reset to `.default` (relaxed mode, review clock running)
    /// and the translation pair pinned to en → zh-Hant. Goes through the
    /// production stores' real write paths (UserDefaults + iCloud KVS layers,
    /// LWW timestamps included) so each launch starts from the same state no
    /// matter what a previous run left behind in the simulator.
    ///
    /// App language is intentionally NOT pinned here: `AppLanguageStore.setLanguage`
    /// schedules `Tips.resetDatastore()` which traps when TipKit is not yet
    /// configured (we run during `App.init`). The UI suite already assumes a
    /// zh-Hant simulator (see `AppPage` tab labels).
    @MainActor
    private static func seedCleanPreferences() {
        ReviewSettingsStore.shared.update(.default)
        TranslationLanguage.currentSource = .en
        TranslationLanguage.currentTarget = .zhHant
        AppLog.app.info("UI-test fixture seeded: settings.cleanPreferences")
    }
}
#endif
