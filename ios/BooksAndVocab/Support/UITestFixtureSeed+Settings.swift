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
}
#endif
