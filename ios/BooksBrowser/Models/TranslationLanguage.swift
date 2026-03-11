import Foundation

enum TranslationLanguage: String, CaseIterable, Identifiable, Codable {
    case en
    case zhHant = "zh-Hant"
    case zhHans = "zh-Hans"
    case ja
    case ko
    case fr
    case de
    case es

    var id: String { rawValue }

    var nativeName: String {
        switch self {
        case .en: return "English"
        case .zhHant: return "繁體中文"
        case .zhHans: return "简体中文"
        case .ja: return "日本語"
        case .ko: return "한국어"
        case .fr: return "Français"
        case .de: return "Deutsch"
        case .es: return "Español"
        }
    }

    var flagEmoji: String {
        switch self {
        case .en: return "🇺🇸"
        case .zhHant: return "🇹🇼"
        case .zhHans: return "🇨🇳"
        case .ja: return "🇯🇵"
        case .ko: return "🇰🇷"
        case .fr: return "🇫🇷"
        case .de: return "🇩🇪"
        case .es: return "🇪🇸"
        }
    }

    static var sourceLanguages: [TranslationLanguage] { [.en, .ja, .ko, .fr, .de, .es] }
    static var targetLanguages: [TranslationLanguage] { [.zhHant, .zhHans, .en, .ja, .ko] }

    // MARK: - UserDefaults persistence

    private static let sourceKey = "translation_source_lang"
    private static let targetKey = "translation_target_lang"

    static var currentSource: TranslationLanguage {
        get {
            guard let raw = UserDefaults.standard.string(forKey: sourceKey) else { return .en }
            return TranslationLanguage(rawValue: raw) ?? .en
        }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: sourceKey) }
    }

    static var currentTarget: TranslationLanguage {
        get {
            guard let raw = UserDefaults.standard.string(forKey: targetKey) else { return .zhHant }
            return TranslationLanguage(rawValue: raw) ?? .zhHant
        }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: targetKey) }
    }
}
