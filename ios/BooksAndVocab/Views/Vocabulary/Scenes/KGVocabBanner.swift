//
//  KGVocabBanner.swift
//  Books & Vocab
//
//  單字本清單頂部提示的「錯誤語意單一真相」＋純函式呈現 factory。
//
//  取代先前 `KGVocabView.bannerState` 對任何 `errorMessage != nil` 一律硬編碼
//  「離線模式，同步失敗」的缺陷（違反 `KGError.isNetworkRelated` 契約，見
//  `KGServiceErrorTests`）：401 / 5xx / 逾時全被謊報成離線且不可重試。
//  現在依實際 error 型別決定文案、glyph 與可否重試；可重試的持續狀態進畫面內
//  面板，一次性通知走頂端 pill（#2047）。
//

import SwiftUI

/// 單字本頂部提示的錯誤語意單一真相。coordinator 只寫這個值，`errorMessage`
/// 由它衍生，UI 由 `KGVocabBanner.panel` / `.pill` 依它產生正確的面板或 pill。
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

/// 純函式呈現 factory，可單元測試（無 View / 無 Network）。依 docs/sop/ui-design.md
/// 「暫時性提示」把同一份狀態拆成兩個出口：
/// - `panel`：需要使用者操作（重試）的**持續狀態** → 清單頂端的畫面內面板。
///   優先序：待刪除 > 可重試的同步錯誤。
/// - `pill`：**一次性通知**（不可重試的錯誤、部分失敗、成功回饋，以及使用者主動
///   刷新後才出現的面板）→ 頂端 pill。
/// 兩者獨立計算：待刪除面板顯示時，「重試仍失敗」之類的通知照樣以 pill 告知，
/// 不再被面板的優先序蓋掉。
enum KGVocabBanner {
    /// 事件 key：同一來源的新結果就地取代舊 pill（例如連續下拉刷新），不排隊疊加。
    enum PillKey {
        static let refresh = "vocab.refresh"
        static let pendingDeletes = "vocab.pendingDeletes"
        static let archive = "vocab.archive"
    }

    static func panel(
        pendingDeleteCount: Int,
        error: KGVocabBannerError?
    ) -> KGVocabPresenter.State.StatusPanel? {
        if pendingDeleteCount > 0 {
            return .init(
                message: L10n.format("%@ 個單字刪除待同步", "\(pendingDeleteCount)"),
                systemImage: "exclamationmark.triangle.fill",
                canDismiss: false
            )
        }
        if case let .refresh(message, isRetryable, isNetworkRelated) = error, isRetryable {
            return .init(
                message: message,
                systemImage: isNetworkRelated ? "wifi.slash" : "exclamationmark.triangle.fill",
                canDismiss: true
            )
        }
        return nil
    }

    /// - Parameter refreshWasExplicit: 最近一次 refresh 由使用者主動觸發。可重試的錯誤
    ///   由面板承載；只有主動觸發時才另彈 pill，進頁自動載入的失敗只顯示面板。
    static func pill(
        error: KGVocabBannerError?,
        refreshSuccessMessage: String?,
        refreshWasExplicit: Bool = false
    ) -> AppToastItem? {
        if let error {
            switch error {
            case let .refresh(message, isRetryable, _):
                guard !isRetryable || refreshWasExplicit else { return nil }
                return AppToastItem(message: message, style: .warning, key: PillKey.refresh)
            case let .pendingDeletesFailure(message):
                return AppToastItem(message: message, style: .warning, key: PillKey.pendingDeletes)
            case let .archivePartial(message):
                return AppToastItem(message: message, style: .warning, key: PillKey.archive)
            }
        }
        if let refreshSuccessMessage {
            return AppToastItem(message: refreshSuccessMessage, style: .success, key: PillKey.refresh)
        }
        return nil
    }
}
