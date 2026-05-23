//
//  KGError.swift
//  BooksBrowser
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
            return L10n.format("HTTP %d：%@", code, detail)
        case .decodingError(let err):
            return L10n.format("解碼錯誤：%@", err.localizedDescription)
        case .networkError(let err):
            return L10n.format("網路錯誤：%@", err.localizedDescription)
        case .serverError(let msg):
            return L10n.format("KG 伺服器錯誤：%@", msg)
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
