#if os(iOS)
import Foundation
import Testing
import SwiftUI
@testable import BooksAndVocab

/// Pins the vocab-list banner presentation contract: the banner must reflect the
/// *actual* error, never hard-code "離線模式". Regression guard for the bug where any
/// `errorMessage != nil` was rendered as an offline banner regardless of the real error
/// (violating the `KGError.isNetworkRelated` contract pinned in `KGServiceErrorTests`).
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

    // MARK: - factory: message must pass through, never hard-coded offline

    @Test func make_nonNetworkError_showsRealMessage_notOffline() {
        let realMessage = KGError.httpError(statusCode: 500, detail: "boom").localizedDescription
        let banner = KGVocabBanner.make(
            pendingDeleteCount: 0,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.httpError(statusCode: 500, detail: "boom")),
            refreshSuccessMessage: nil
        )
        #expect(banner?.message == realMessage)
        // The old hard-coded offline copy must NOT appear for a non-network error.
        #expect(banner?.message != L10n.string("離線模式，同步失敗。請確認網路連線後重試"))
        // Non-network error uses the generic warning glyph, not the wifi.slash offline glyph.
        #expect(banner?.systemImage != "wifi.slash")
        // 5xx is retryable.
        #expect(banner?.canRetry == true)
    }

    @Test func make_unauthorized_isNotRetryable() {
        let banner = KGVocabBanner.make(
            pendingDeleteCount: 0,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.unauthorized),
            refreshSuccessMessage: nil
        )
        #expect(banner?.message == KGError.unauthorized.localizedDescription)
        #expect(banner?.canRetry == false)
        #expect(banner?.systemImage != "wifi.slash")
    }

    @Test func make_offlineError_usesOfflineGlyphAndRetry() {
        let banner = KGVocabBanner.make(
            pendingDeleteCount: 0,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.offline),
            refreshSuccessMessage: nil
        )
        #expect(banner?.message == KGError.offline.localizedDescription)
        #expect(banner?.systemImage == "wifi.slash")
        #expect(banner?.canRetry == true)
        #expect(banner?.tone == .warning)
    }

    // MARK: - factory: priority ordering preserved

    @Test func make_pendingDeletes_takesPriorityOverError() {
        let banner = KGVocabBanner.make(
            pendingDeleteCount: 3,
            error: KGVocabBannerErrorClassifier.refreshError(from: KGError.offline),
            refreshSuccessMessage: nil
        )
        #expect(banner?.canRetry == true)
        #expect(banner?.canDismiss == false)
        #expect(banner?.message == L10n.format("%@ 個單字刪除待同步", "3"))
    }

    @Test func make_successMessage_whenNoErrorOrDeletes() {
        let banner = KGVocabBanner.make(
            pendingDeleteCount: 0,
            error: nil,
            refreshSuccessMessage: L10n.string("單字庫已更新")
        )
        #expect(banner?.tone == .success)
        #expect(banner?.systemImage == "checkmark.circle.fill")
    }

    @Test func make_returnsNil_whenNothingToShow() {
        let banner = KGVocabBanner.make(pendingDeleteCount: 0, error: nil, refreshSuccessMessage: nil)
        #expect(banner == nil)
    }
}
#endif
