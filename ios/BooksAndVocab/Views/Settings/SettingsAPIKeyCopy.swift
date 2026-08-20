import Foundation

enum SettingsAPIKeyPresentation {
    static func shouldShowManagement(isLoggedIn: Bool, isProActive: Bool) -> Bool {
        isLoggedIn && isProActive
    }
}

enum SettingsAPIKeyCopy {
    static var rowTitle: String { L10n.string("外部 API 金鑰") }
    static var rowSubtitle: String { L10n.string("連接閱讀器與自動化工具") }
    static var navigationTitle: String { L10n.string("API 金鑰") }
    static var sectionTitle: String { L10n.string("你的 API 金鑰") }
    static var description: String {
        L10n.string("API 金鑰只會在建立時顯示一次。請立即複製並保存；離開此頁後無法再次查看完整金鑰。")
    }
    static var createButtonTitle: String { L10n.string("建立 API 金鑰") }
    static var labelFieldTitle: String { L10n.string("用途標籤") }
    static var labelPlaceholder: String { L10n.string("例如：閱讀器自動上傳") }
    static var cancelTitle: String { L10n.string("取消") }
    static var copyTitle: String { L10n.string("複製金鑰") }
    static var copiedToast: String { L10n.string("API 金鑰已複製") }
    static var newKeyTitle: String { L10n.string("新金鑰只顯示這一次") }
    static var oneTimeWarning: String { L10n.string("若現在不複製，之後只能撤銷並建立新的金鑰。") }
    static var activeTitle: String { L10n.string("使用中") }
    static var revokedTitle: String { L10n.string("已撤銷") }
    static var revokeTitle: String { L10n.string("撤銷") }
    static var revokeConfirmationTitle: String { L10n.string("撤銷這組 API 金鑰？") }
    static var revokeConfirmationMessage: String {
        L10n.string("撤銷後，使用這組金鑰的外部工具將無法再存取你的資料。")
    }
    static var emptyTitle: String { L10n.string("尚未建立 API 金鑰") }
    static var emptyDescription: String { L10n.string("建立一組金鑰，讓外部閱讀器或自動化工具連接你的 Pro 帳號。") }
    static var proRequired: String { L10n.string("API 金鑰管理需要有效的 Pro 權限。") }
    static var retryTitle: String { L10n.string("重試") }
    static var offline: String { L10n.string("目前離線，無法管理 API 金鑰。") }
    static var rateLimited: String { L10n.string("請稍候再試，API 金鑰管理目前受到限速保護。") }
    static var genericError: String { L10n.string("API 金鑰管理暫時失敗，請稍後再試。") }

    static func createdAt(_ rawValue: String) -> String {
        if let date = AppDateFormatters.iso8601.date(from: rawValue) {
            return L10n.format("建立於 %@", date.formatted(date: .abbreviated, time: .shortened))
        }
        return L10n.format("建立於 %@", rawValue)
    }

    static func errorMessage(for error: Error) -> String {
        guard let error = error as? KGError else { return genericError }
        switch error {
        case .offline:
            return offline
        case .unauthorized, .notAuthenticated:
            return L10n.string("登入已過期，請重新登入後再試。")
        case .httpError(let statusCode, _):
            switch statusCode {
            case 403:
                return proRequired
            case 429:
                return rateLimited
            default:
                return genericError
            }
        case .networkError:
            return genericError
        case .decodingError, .serverError:
            return genericError
        }
    }
}
