import Foundation

enum L10n {
    // UUID-style sentinel to avoid colliding with any plausible localized value.
    private static let missSentinel = "__L10N_MISS_8F3A2B__"

    private static let enBundle: Bundle? = {
        guard let path = Bundle.main.path(forResource: "en", ofType: "lproj") else { return nil }
        return Bundle(path: path)
    }()

    /// Three-tier lookup: current language bundle → en bundle → key itself.
    /// Why: 缺鍵時回中文 key 原文會在非 CJK locale 漏出中文字面,違反在地化品質。
    private static func lookup(_ key: String) -> String {
        let current = AppLanguageStore.shared.stringBundle
        let primary = current.localizedString(forKey: key, value: missSentinel, table: "Localizable")
        if primary != missSentinel { return primary }
        if let enBundle {
            let secondary = enBundle.localizedString(forKey: key, value: missSentinel, table: "Localizable")
            if secondary != missSentinel { return secondary }
        }
        return key
    }

    static func string(_ key: String) -> String {
        lookup(key)
    }

    /// Format via NSString so that String Catalog / .stringsdict plural variations
    /// (NSStringPluralRuleType) are triggered by `%lld` arguments. Callers should pass
    /// Int64 with `%lld` to ensure 32/64-bit alignment.
    static func format(_ key: String, _ arguments: any CVarArg...) -> String {
        let format = lookup(key)
        return withVaList(arguments) { va in
            NSString(format: format, locale: AppLanguageStore.shared.formatLocale, arguments: va) as String
        }
    }
}

extension String {
    var localized: String {
        L10n.string(self)
    }
}
