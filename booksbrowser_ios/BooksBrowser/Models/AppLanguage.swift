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
            return "跟隨系統"
        case .english:
            return "English"
        case .traditionalChinese:
            return "繁體中文"
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

    private init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let raw = defaults.string(forKey: Keys.selectedLanguage),
           let selection = AppLanguage(rawValue: raw) {
            self.selection = selection
        } else {
            self.selection = .system
        }
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
