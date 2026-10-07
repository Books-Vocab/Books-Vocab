#if os(iOS)
import Foundation
import Testing
import SwiftUI
@testable import BooksAndVocab

/// Pins the vocab-list notice presentation contract: it must reflect the
/// *actual* error, never hard-code "離線模式". Regression guard for the bug where any
/// `errorMessage != nil` was rendered as an offline banner regardless of the real error
/// (violating the `KGError.isNetworkRelated` contract pinned in `KGServiceErrorTests`).
/// Since #2047 the same state splits into an actionable in-screen panel (retryable)
/// and one-off top pills (everything else).
@MainActor
@Suite("KGVocabBanner presentation")
struct KGVocabBannerTests {

    // MARK: - classifier

    @Test func classify_offline_isNetworkAndRetryable() {
        let c = KGVocabBannerErrorClassifier.classify(KGError.offline)
        #expect(c.isNetworkRelated)
        #expect(c.isRetryable)
    }

    @Test func classify_unauthorized_isNotNetworkNorRetryable() {
        let c = KGVocabBannerErrorClassifier.classify(KGError.unauthorized)
        #expect(!c.isNetworkRelated)
        #expect(!c.isRetryable)
    }

    @Test func classify_httpServerError_isRetryableNotNetwork() {
        let c = KGVocabBannerErrorClassifier.classify(KGError.httpError(statusCode: 500, detail: "boom"))
        #expect(!c.isNetworkRelated)
        #expect(c.isRetryable)
    }

    @Test func classify_urlTimeout_isNetworkAndRetryable() {
        let c = KGVocabBannerErrorClassifier.classify(URLError(.timedOut))
        #expect(c.isNetworkRelated)
        #expect(c.isRetryable)
    }

    // MARK: - panel: message must pass through, never hard-coded offline

    @Test func panel_nonNetworkRetryableError_showsRealMessage_notOffline() {
        let realMessage = KGError.httpError(statusCode: 500, detail: "boom").localizedDescription
        let panel = KGVocabBanner.panel(
            pendingDeleteCount: 0,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.httpError(statusCode: 500, detail: "boom"))
        )
        // 5xx is retryable → it is an actionable state, so it lives in the panel.
        #expect(panel?.message == realMessage)
        // The old hard-coded offline copy must NOT appear for a non-network error.
        #expect(panel?.message != L10n.string("離線模式，同步失敗。請確認網路連線後重試"))
        // Non-network error uses the generic warning glyph, not the wifi.slash offline glyph.
        #expect(panel?.systemImage != "wifi.slash")
        #expect(panel?.canDismiss == true)
    }

    @Test func panel_offlineError_usesOfflineGlyph() {
        let panel = KGVocabBanner.panel(
            pendingDeleteCount: 0,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.offline)
        )
        #expect(panel?.message == KGError.offline.localizedDescription)
        #expect(panel?.systemImage == "wifi.slash")
    }

    @Test func panel_pendingDeletes_takesPriorityOverError() {
        let panel = KGVocabBanner.panel(
            pendingDeleteCount: 3,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.offline)
        )
        #expect(panel?.canDismiss == false)
        #expect(panel?.message == L10n.format("%@ 個單字刪除待同步", "3"))
    }

    @Test func panel_notShownForOneOffNotices() {
        // Not retryable / partial failures / success are notifications, not states.
        #expect(KGVocabBanner.panel(
            pendingDeleteCount: 0,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.unauthorized)
        ) == nil)
        #expect(KGVocabBanner.panel(
            pendingDeleteCount: 0,
            error: .pendingDeletesFailure(message: "x")
        ) == nil)
        #expect(KGVocabBanner.panel(
            pendingDeleteCount: 0,
            error: .archivePartial(message: "x")
        ) == nil)
        #expect(KGVocabBanner.panel(pendingDeleteCount: 0, error: nil) == nil)
    }

    // MARK: - pill: one-off notices

    @Test func pill_unauthorized_isOneOffWarning_notOffline() {
        let pill = KGVocabBanner.pill(
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.unauthorized),
            refreshSuccessMessage: nil
        )
        #expect(pill?.message == KGError.unauthorized.localizedDescription)
        #expect(pill?.style == .warning)
        #expect(pill?.key == KGVocabBanner.PillKey.refresh)
    }

    @Test func pill_retryableErrorFromAutomaticLoad_isCarriedByPanelOnly() {
        let pill = KGVocabBanner.pill(
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.offline),
            refreshSuccessMessage: nil,
            refreshWasExplicit: false
        )
        #expect(pill == nil)
    }

    @Test func pill_retryableErrorFromUserRefresh_alsoNotifies() {
        // The panel appears as the result of a user action → announce it with a pill too.
        let pill = KGVocabBanner.pill(
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.offline),
            refreshSuccessMessage: nil,
            refreshWasExplicit: true
        )
        #expect(pill?.message == KGError.offline.localizedDescription)
        #expect(pill?.style == .warning)
        #expect(pill?.key == KGVocabBanner.PillKey.refresh)
    }

    @Test func pill_pendingDeleteFailure_isShownEvenWhilePanelIsUp() {
        // Previously the pending-delete banner's priority hid this result.
        let message = L10n.format("刪除失敗 %@ 筆，稍後將自動重試", "2")
        let pill = KGVocabBanner.pill(error: .pendingDeletesFailure(message: message), refreshSuccessMessage: nil)
        #expect(pill?.message == message)
        #expect(pill?.style == .warning)
        #expect(pill?.key == KGVocabBanner.PillKey.pendingDeletes)
        #expect(KGVocabBanner.panel(pendingDeleteCount: 2, error: .pendingDeletesFailure(message: message)) != nil)
    }

    @Test func pill_archivePartial_isWarning() {
        let pill = KGVocabBanner.pill(error: .archivePartial(message: "1/3"), refreshSuccessMessage: nil)
        #expect(pill?.style == .warning)
        #expect(pill?.key == KGVocabBanner.PillKey.archive)
    }

    @Test func pill_successMessage_whenNoError() {
        let pill = KGVocabBanner.pill(error: nil, refreshSuccessMessage: L10n.string("單字庫已更新"))
        #expect(pill?.style == .success)
        #expect(pill?.message == L10n.string("單字庫已更新"))
        // Same event key as refresh errors: a newer refresh result replaces the older pill.
        #expect(pill?.key == KGVocabBanner.PillKey.refresh)
    }

    @Test func pill_errorWinsOverStaleSuccess() {
        let pill = KGVocabBanner.pill(
            error: .archivePartial(message: "1/3"),
            refreshSuccessMessage: L10n.string("單字庫已更新")
        )
        #expect(pill?.message == "1/3")
    }

    @Test func pill_returnsNil_whenNothingToShow() {
        #expect(KGVocabBanner.pill(error: nil, refreshSuccessMessage: nil) == nil)
    }
}
#endif
