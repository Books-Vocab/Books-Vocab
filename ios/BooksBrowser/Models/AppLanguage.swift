import Foundation
import SwiftUI

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

    var locale: Locale {
        selection.locale
    }

    var stringBundle: Bundle {
        bundle(for: effectiveLanguage)
    }

    var formatLocale: Locale {
        effectiveLanguage.locale
    }

    func setLanguage(_ language: AppLanguage) {
        guard selection != language else { return }
        selection = language
        defaults.set(language.rawValue, forKey: Keys.selectedLanguage)
        cloud.set(language.rawValue, forKey: Keys.selectedLanguage)
    }

    private var effectiveLanguage: AppLanguage {
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
}
