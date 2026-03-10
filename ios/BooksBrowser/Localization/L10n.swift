import Foundation

enum L10n {
    static func string(_ key: String) -> String {
        AppLanguageStore.shared.stringBundle.localizedString(forKey: key, value: key, table: "Localizable")
    }

    static func format(_ key: String, _ arguments: CVarArg...) -> String {
        let format = string(key)
        return String(format: format, locale: AppLanguageStore.shared.formatLocale, arguments: arguments)
    }
}

extension String {
    var localized: String {
        L10n.string(self)
    }
}
