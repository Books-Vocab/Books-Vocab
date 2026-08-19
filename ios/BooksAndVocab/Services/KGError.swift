//
//  KGError.swift
//  Books & Vocab
//
//  KG API client error type.
//

import Foundation

enum KGError: LocalizedError {
    case notAuthenticated
    case unauthorized
    case offline
    case httpError(statusCode: Int, detail: String)
    case decodingError(underlying: Error)
    case networkError(underlying: Error)
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .notAuthenticated, .unauthorized:
            return L10n.string("未登入帳號或身份已過期")
        case .offline:
            return L10n.string("目前沒有網路連線")
        case .httpError(let code, let detail):
            return L10n.format("HTTP %@：%@", String(code), detail)
        case .decodingError(let err):
            return L10n.format("解碼錯誤：%@", err.localizedDescription)
        case .networkError(let err):
            return L10n.format("網路錯誤：%@", err.localizedDescription)
        case .serverError(let msg):
            return L10n.format("Books & Vocab 服務錯誤：%@", msg)
        }
    }

    var isNetworkRelated: Bool {
        switch self {
        case .offline, .networkError: return true
        default: return false
        }
    }

    var isRetryable: Bool {
        switch self {
        case .httpError(let code, _): return (500...599).contains(code) || code == 429
        case .offline, .networkError: return true
        default: return false
        }
    }
}

enum SyncFailurePresentation {
    static func message(label: String, error: Error) -> String {
        message(label: label, error: error, language: AppLanguageStore.shared.selection)
    }

    /// Explicit language keeps presentation contracts deterministic without
    /// changing the application's selected language.
    static func message(label: String, error: Error, language: AppLanguage) -> String {
        L10n.format(
            "sync.failure.message",
            language: language,
            operationTitle(for: label, language: language),
            reasonTitle(for: error, language: language)
        )
    }

    private static func operationTitle(for label: String, language: AppLanguage) -> String {
        switch label {
        case "pushReview":
            return L10n.string("sync.failure.operation.pushReview", language: language)
        case "pushReviewEvents":
            return L10n.string("sync.failure.operation.pushReviewEvents", language: language)
        case "pull":
            return L10n.string("sync.failure.operation.pull", language: language)
        case "pullReviewEvents":
            return L10n.string("sync.failure.operation.pullReviewEvents", language: language)
        default:
            return L10n.string("sync.failure.operation.generic", language: language)
        }
    }

    /// 只取「為什麼失敗」，不帶「哪個操作失敗」的前綴。
    ///
    /// 給逐步同步清單用：那一列本身就是操作名，`message(label:error:)` 的
    /// 「『下載單字』失敗：…」在該處會把操作名說第二遍。更重要的是它擋住了
    /// `error.localizedDescription` 這條捷徑——後者對 `CancellationError` 會吐
    /// 英文的「The operation couldn't be completed.」，對 `KGError.httpError`
    /// 會把內部 path（"GET api/vocab failed"）漏到使用者眼前。
    static func reason(for error: Error) -> String {
        reason(for: error, language: AppLanguageStore.shared.selection)
    }

    static func reason(for error: Error, language: AppLanguage) -> String {
        reasonTitle(for: error, language: language)
    }

    private static func reasonTitle(for error: Error, language: AppLanguage) -> String {
        if let kgError = error as? KGError {
            return reasonTitle(for: kgError, language: language)
        }
        if let urlError = error as? URLError {
            return reasonTitle(for: urlError, language: language)
        }
        return L10n.string("sync.failure.reason.unknown", language: language)
    }

    private static func reasonTitle(for error: KGError, language: AppLanguage) -> String {
        switch error {
        case .notAuthenticated, .unauthorized:
            return L10n.string("sync.failure.reason.authExpired", language: language)
        case .offline:
            return L10n.string("sync.failure.reason.offline", language: language)
        case .networkError(let underlying):
            if let urlError = underlying as? URLError {
                return reasonTitle(for: urlError, language: language)
            }
            return L10n.string("sync.failure.reason.network", language: language)
        case .httpError(let statusCode, _):
            if statusCode == 429 {
                return L10n.string("sync.failure.reason.rateLimited", language: language)
            }
            if (500...599).contains(statusCode) {
                return L10n.string("sync.failure.reason.serverUnavailable", language: language)
            }
            // 4xx（非 429）帶上 status code，提供可觀測性 — 多數是契約/請求問題，
            // code 是定位的關鍵線索（見 review-event pull 死鎖案）。
            return L10n.format(
                "sync.failure.reason.serverRejectedCode",
                language: language,
                String(statusCode)
            )
        case .decodingError:
            return L10n.string("sync.failure.reason.decoding", language: language)
        case .serverError:
            return L10n.string("sync.failure.reason.server", language: language)
        }
    }

    private static func reasonTitle(for error: URLError, language: AppLanguage) -> String {
        switch error.code {
        case .notConnectedToInternet:
            return L10n.string("sync.failure.reason.offline", language: language)
        case .timedOut:
            return L10n.string("sync.failure.reason.timeout", language: language)
        case .networkConnectionLost, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
            return L10n.string("sync.failure.reason.network", language: language)
        default:
            return L10n.string("sync.failure.reason.network", language: language)
        }
    }
}
