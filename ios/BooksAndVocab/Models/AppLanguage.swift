import Foundation
import SwiftUI
import TipKit

enum AppLanguage: String, CaseIterable, Identifiable {
    case system
    case english
    case traditionalChinese
    case simplifiedChinese
    case japanese
    case korean

    var id: String { rawValue }

    var localizationCode: String? {
        switch self {
        case .system:
            return nil
        case .english:
            return "en"
        case .traditionalChinese:
            return "zh-Hant"
        case .simplifiedChinese:
            return "zh-Hans"
        case .japanese:
            return "ja"
        case .korean:
            return "ko"
        }
    }

    var locale: Locale {
        switch self {
        case .system:
            return .autoupdatingCurrent
        case .english:
            return Locale(identifier: "en")
        case .traditionalChinese:
            return Locale(identifier: "zh-Hant")
        case .simplifiedChinese:
            return Locale(identifier: "zh-Hans")
        case .japanese:
            return Locale(identifier: "ja")
        case .korean:
            return Locale(identifier: "ko")
        }
    }

    var titleKey: String {
        switch self {
        case .system:
            return L10n.string("跟隨系統")
        case .english:
            return L10n.string("English")
        case .traditionalChinese:
            return L10n.string("繁體中文")
        case .simplifiedChinese:
            return L10n.string("简体中文")
        case .japanese:
            return L10n.string("日本語")
        case .korean:
            return L10n.string("한국어")
        }
    }

    static func resolvedSystemLanguage() -> AppLanguage {
        guard let preferred = Locale.preferredLanguages.first?.lowercased() else {
            return .english
        }

        if preferred.hasPrefix("zh-hant") {
            return .traditionalChinese
        }
        if preferred.hasPrefix("zh-hans") {
            return .simplifiedChinese
        }
        if preferred.hasPrefix("ja") {
            return .japanese
        }
        if preferred.hasPrefix("ko") {
            return .korean
        }
        if preferred.hasPrefix("en") {
            return .english
        }
        return .english
    }
}

final class AppLanguageStore: ObservableObject {
    static let shared = AppLanguageStore()

    private enum Keys {
        static let selectedLanguage = "app_language_selection"
    }

    @Published private(set) var selection: AppLanguage

    private let defaults: UserDefaults
    private let cloud = CloudPreferencesSync.shared
    private var cloudObserver: Any?

    private init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let raw = cloud.string(forKey: Keys.selectedLanguage) ?? defaults.string(forKey: Keys.selectedLanguage)
        if let raw, let selection = AppLanguage(rawValue: raw) {
            self.selection = selection
        } else {
            self.selection = .system
        }
        cloudObserver = NotificationCenter.default.addObserver(
            forName: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: NSUbiquitousKeyValueStore.default,
            queue: .main
        ) { [weak self] notification in
            guard let self,
                  let keys = notification.userInfo?[NSUbiquitousKeyValueStoreChangedKeysKey] as? [String],
                  keys.contains(Keys.selectedLanguage),
                  let raw = self.cloud.string(forKey: Keys.selectedLanguage),
                  let value = AppLanguage(rawValue: raw),
                  value != self.selection
            else { return }
            self.selection = value
        }
    }

    deinit {
        if let cloudObserver { NotificationCenter.default.removeObserver(cloudObserver) }
    }

    // MARK: - Locale Resolution
    //
    // 本 store 暴露三條 locale-related path,分流意圖刻意保留:
    //
    // 1. `locale` (-> SwiftUI `.environment(\.locale, ...)`):
    //    當 selection == .system 回 `.autoupdatingCurrent`。
    //    Why: SwiftUI environment 透過 KVO observe locale 變更,使用者改系統 region
    //    時(無需重啟 App)需即時 propagate 到所有 view。`Locale(identifier:)` 是
    //    immutable snapshot,會錯失系統設定變更。
    //
    // 2. `formatLocale` (-> `String.format` / `NSString(format:locale:)` / Date.FormatStyle.locale):
    //    當 selection == .system 走 `effectiveLanguage.locale`,亦即先 resolve 出具體
    //    語言再回 immutable locale。
    //    Why: 字串格式化需要對應到一個 *具體* 語言的 plural rule / 數字 / 日期格式。
    //    `.autoupdatingCurrent` 在 format 上下文不穩(每次讀都是「最新系統值」),
    //    且 plural rule 引擎不接受 auto-updating locale。
    //
    // 3. `stringBundle` (-> `Bundle.localizedString(forKey:)`):
    //    走 `effectiveLanguage` resolve 到對應 .lproj。系統語言不在我們支援清單
    //    時(例如 fr / de),`resolvedSystemLanguage` fallback 回 .english。
    //
    // 規則: 任何 user-visible 字串/格式 → 走 `stringBundle` + `formatLocale`;
    // 任何 SwiftUI 注入(`.environment(\.locale, ...)`) → 走 `locale`。
    var locale: Locale {
        selection.locale
    }

    /// 實際走 `Bundle.main.path(forResource:)` 解析的次數。測試以此釘住
    /// 快取契約（穩定語言下重複讀取不得重解析）。
    private(set) var bundleResolutionCount = 0

    /// 每語言解析一次後永久快取。`Bundle(path:)` 本身有 NSBundle 內部快取，
    /// 但 `path(forResource:)` 的字串/檔案系統解析沒有——device time-profile
    /// (2026-06-10) 顯示 L10n.lookup 在複習卡 settle 重評時每字串都付這筆,
    /// 一幀內呼叫數十次。key 是 resolve 後的具體語言,.system 的系統語言
    /// 變更會落到不同 key,不會黏住舊值。lock 防 L10n 從非主執行緒讀取
    /// 時 dict 競寫。
    private let bundleCacheLock = NSLock()
    private var bundleCache: [AppLanguage: Bundle] = [:]

    var stringBundle: Bundle {
        let language = effectiveLanguage
        bundleCacheLock.lock()
        defer { bundleCacheLock.unlock() }
        if let cached = bundleCache[language] { return cached }
        bundleResolutionCount += 1
        let resolved = bundle(for: language)
        bundleCache[language] = resolved
        return resolved
    }

    var formatLocale: Locale {
        effectiveLanguage.locale
    }

    func setLanguage(_ language: AppLanguage) {
        guard selection != language else { return }
        selection = language
        defaults.set(language.rawValue, forKey: Keys.selectedLanguage)
        cloud.set(language.rawValue, forKey: Keys.selectedLanguage)
        // TipKit datastore caches rendered Text — without reset, already-shown tips
        // would still display the previous-language strings on next presentation.
        // UX trade-off: resetDatastore() wipes **both** `MaxDisplayCount` progress
        // AND `Event` donation history. So:
        //  - Previously dismissed tips may re-appear once.
        //  - Rules of form `{ donations.count == 0 }` (e.g. LongPressTip) re-pass,
        //    so power users who've already used the feature could see the tip
        //    again. Acceptable cost for getting in-language text on next show.
        Task {
            do {
                try Tips.resetDatastore()
            } catch {
                #if DEBUG
                if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] == nil {
                    assertionFailure("Tips.resetDatastore failed: \(error)")
                } else {
                    debugPrint("Tips.resetDatastore skipped during tests: \(error)")
                }
                #endif
            }
        }
    }

    /// The concrete language to apply for bundle/font/format decisions.
    /// `.system` resolves to whichever supported language matches the OS preference.
    /// Internal scope: AppFonts cascade selection reads this to pick per-script
    /// CJK fallback fonts.
    var effectiveLanguage: AppLanguage {
        switch selection {
        case .system:
            return AppLanguage.resolvedSystemLanguage()
        case .english, .traditionalChinese, .simplifiedChinese, .japanese, .korean:
            return selection
        }
    }

    private func bundle(for language: AppLanguage) -> Bundle {
        guard
            let code = language.localizationCode,
            let path = Bundle.main.path(forResource: code, ofType: "lproj"),
            let bundle = Bundle(path: path)
        else {
            return .main
        }
        return bundle
    }

    private init(previewSelection: AppLanguage) {
        self.defaults = UserDefaults(suiteName: "preview.language") ?? .standard
        self.selection = previewSelection
        // No cloudObserver — Preview / Catalog scenarios don't sync with iCloud
        // and skipping the observer avoids polluting NotificationCenter in tests.
    }

    static let preview = AppLanguageStore(previewSelection: .system)
}
