import Foundation
import SwiftUI

enum AppLanguage: String, CaseIterable, Identifiable {
    case system
    case english
    case traditionalChinese

    var id: String { rawValue }

    var localizationCode: String? {
        switch self {
        case .system:
            return nil
        case .english:
            return "en"
        case .traditionalChinese:
            return "zh-Hant"
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
        }
    }

    static func resolvedSystemLanguage() -> AppLanguage {
        guard let preferred = Locale.preferredLanguages.first?.lowercased() else {
            return .english
        }

        if preferred.hasPrefix("zh-hant") {
            return .traditionalChinese
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

    private init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let raw = cloud.string(forKey: Keys.selectedLanguage) ?? defaults.string(forKey: Keys.selectedLanguage)
        if let raw, let selection = AppLanguage(rawValue: raw) {
            self.selection = selection
        } else {
            self.selection = .system
        }
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleCloudChange(_:)),
            name: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: NSUbiquitousKeyValueStore.default
        )
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    @objc private func handleCloudChange(_ notification: Notification) {
        guard let keys = notification.userInfo?[NSUbiquitousKeyValueStoreChangedKeysKey] as? [String],
              keys.contains(Keys.selectedLanguage),
              let raw = cloud.string(forKey: Keys.selectedLanguage),
              let value = AppLanguage(rawValue: raw),
              value != selection
        else { return }
        DispatchQueue.main.async { self.selection = value }
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
        case .english, .traditionalChinese:
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
