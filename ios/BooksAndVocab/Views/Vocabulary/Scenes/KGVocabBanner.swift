//
//  KGVocabBanner.swift
//  Books & Vocab
//
//  單字本清單頂部 banner 的「錯誤語意單一真相」＋純函式呈現 factory。
//
//  取代先前 `KGVocabView.bannerState` 對任何 `errorMessage != nil` 一律硬編碼
//  「離線模式，同步失敗」的缺陷（違反 `KGError.isNetworkRelated` 契約，見
//  `KGServiceErrorTests`）：401 / 5xx / 逾時全被謊報成離線且不可重試。
//  現在 banner 依實際 error 型別決定文案、glyph 與可否重試。
//

import SwiftUI

/// 單字本 banner 的錯誤語意單一真相。coordinator 只寫這個值，`errorMessage`
/// 由它衍生，UI 由 `KGVocabBanner.make` 依它產生正確 banner。
enum KGVocabBannerError: Equatable {
    /// `forceRefresh` / pull 失敗。`message` 為已本地化的錯誤描述；旗標決定 glyph 與可否重試。
    case refresh(message: String, isRetryable: Bool, isNetworkRelated: Bool)
    /// `retryPendingDeletes` 部分失敗（自動重試語意）。
    case pendingDeletesFailure(message: String)
    /// 批次封存部分失敗。
    case archivePartial(message: String)

    var message: String {
        switch self {
        case let .refresh(message, _, _): return message
        case let .pendingDeletesFailure(message): return message
        case let .archivePartial(message): return message
        }
    }
}

/// 把任意 `Error` 分類為 banner 需要的旗標，重用 `KGError` 既有語意契約
/// （`KGServiceErrorTests` pin：auth/http/decode 非 network、5xx/429/network 可重試）。
enum KGVocabBannerErrorClassifier {
    static func classify(_ error: Error) -> (isRetryable: Bool, isNetworkRelated: Bool) {
        if let kg = error as? KGError {
            return (kg.isRetryable, kg.isNetworkRelated)
        }
        if let url = error as? URLError {
            let networkCodes: Set<URLError.Code> = [
                .notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost,
                .cannotFindHost, .dnsLookupFailed, .timedOut, .dataNotAllowed,
            ]
            let isNetwork = networkCodes.contains(url.code)
            return (isNetwork, isNetwork)
        }
        return (false, false)
    }

    /// 由 `forceRefresh` catch 呼叫：把 error 轉為 `.refresh` case，文案用其
    /// `localizedDescription`（`KGError.errorDescription` 已提供各型別的正確本地化文案）。
    static func refreshError(from error: Error) -> KGVocabBannerError {
        let c = classify(error)
        return .refresh(
            message: error.localizedDescription,
            isRetryable: c.isRetryable,
            isNetworkRelated: c.isNetworkRelated
        )
    }
}

/// 純函式 banner factory。優先序：待刪除 > 錯誤 > 成功。可單元測試（無 View / 無 Network）。
enum KGVocabBanner {
    static func make(
        pendingDeleteCount: Int,
        error: KGVocabBannerError?,
        refreshSuccessMessage: String?
    ) -> KGVocabPresenter.State.Banner? {
        if pendingDeleteCount > 0 {
            return .init(
                message: L10n.format("%@ 個單字刪除待同步", "\(pendingDeleteCount)"),
                systemImage: "exclamationmark.triangle.fill",
                tone: .warning,
                canDismiss: false,
                canRetry: true
            )
        }
        if let error {
            switch error {
            case let .refresh(message, isRetryable, isNetworkRelated):
                return .init(
                    message: message,
                    systemImage: isNetworkRelated ? "wifi.slash" : "exclamationmark.triangle.fill",
                    tone: .warning,
                    canDismiss: true,
                    canRetry: isRetryable
                )
            case let .pendingDeletesFailure(message):
                return .init(
                    message: message,
                    systemImage: "exclamationmark.triangle.fill",
                    tone: .warning,
                    canDismiss: true,
                    canRetry: false
                )
            case let .archivePartial(message):
                return .init(
                    message: message,
                    systemImage: "exclamationmark.triangle.fill",
                    tone: .warning,
                    canDismiss: true,
                    canRetry: false
                )
            }
        }
        if let refreshSuccessMessage {
            return .init(
                message: refreshSuccessMessage,
                systemImage: "checkmark.circle.fill",
                tone: .success,
                canDismiss: true,
                canRetry: false
            )
        }
        return nil
    }
}
