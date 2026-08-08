#if os(iOS)
import Foundation
import SwiftData
@testable import BooksAndVocab

/// 共用的 `KGServing` 測試替身。
///
/// 既有慣例是每個測試檔各自寫一份 42 個成員的 `private final class StubKGService`
/// （見 `PodcastPlayerLoaderTests` / `SettingsCoordinatorReviewClockTests`）。第四份
/// 手抄本沒有意義，故此處抽成共用替身：被測方法由**可注入的 handler** 決定行為，其餘
/// 一律 `fatalError("unused")` —— 大聲失敗，好過讓沒預期到的呼叫靜默通過。
///
/// 例外（沿用既有 stub 慣例，回傳無害值而非 trap）：`backgroundSync` / `healthCheck` /
/// `currentAuthToken` / `pushReviewQuietly` / `clearLocalData` / `fetchQuota` /
/// `pullCopiedDeck`。這幾個是背景雜訊型呼叫，trap 它們會讓無關測試炸開。
///
/// 關鍵設計：handler 讓替身能**模擬失敗**。若替身只會成功，rollback 這條失效路徑
/// 就從模型裡消失了，測試會對它永遠綠燈。
final class SpyKGService: KGServing {

    // MARK: - Recorded calls

    struct ArchiveCall: Equatable {
        let word: String
        let archived: Bool
        let notebookId: String
    }

    private(set) var archiveCalls: [ArchiveCall] = []

    /// 預設成功；測 rollback 時注入會 throw 的 handler。
    var archiveCardHandler: (ArchiveCall) throws -> Void = { _ in }

    func archiveCard(word: String, archived: Bool, notebookId: String) async throws {
        let call = ArchiveCall(word: word, archived: archived, notebookId: notebookId)
        archiveCalls.append(call)
        try archiveCardHandler(call)
    }

    // MARK: - BackgroundSyncing

    var lastBackgroundSyncError: String?
    func backgroundSync(container: ModelContainer) async {}

    // MARK: - DeckCopying

    func copyDeck(deckId: String, idempotencyKey: String, notebookName: String?) async throws -> DeckCopyResponse {
        fatalError("unused")
    }

    // MARK: - KGServing properties

    var serverURL: String = "https://example.com"
    var isConnected: Bool = true
    var lastSyncDate: Date?
    var serverCardCount: Int = 0
    var sessionExpiredReason: String?

    // MARK: - KGServing methods (unused by the tests that inject this spy)

    func currentAuthToken() async throws -> String { "token" }
    func authTokenWithoutInvalidation() async -> String? { "token" }
    func healthCheck() async {}
    func batchAdd(entries: [VocabularyEntry], notebookId: String) async throws -> KGAddResponse { fatalError("unused") }
    func triggerPipeline(notebookId: String) async throws { fatalError("unused") }
    @discardableResult
    func pullCardsToLocal(
        container: ModelContainer,
        progress: ((String, Int, Int) -> Void)?,
        notebookId: String?
    ) async throws -> KGPullOutcome { fatalError("unused") }
    func fetchNotebooks() async throws -> [KGNotebook] { fatalError("unused") }
    func createNotebook(name: String, color: String?, coverPattern: String?) async throws -> KGNotebook {
        fatalError("unused")
    }
    func updateNotebook(id: String, name: String?, color: String?, coverPattern: String?) async throws -> KGNotebook {
        fatalError("unused")
    }
    func deleteNotebook(id: String) async throws { fatalError("unused") }
    func fetchUserConfig() async throws -> KGUserConfig { fatalError("unused") }
    func fetchEntitlements() async throws -> KGEntitlements { fatalError("unused") }
    func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements {
        fatalError("unused")
    }
    func updateTranslationConfig(_ translationConfig: KGTranslationConfig) async throws -> KGUserConfig {
        fatalError("unused")
    }
    func updateReviewClockConfig(_ reviewClock: KGReviewClockConfig) async throws -> KGUserConfig { fatalError("unused") }
    func updateReviewModeConfig(_ reviewMode: KGReviewModeConfig) async throws -> KGUserConfig { fatalError("unused") }
    func updateVocabUIConfig(_ vocabUI: KGVocabUIConfig) async throws -> KGUserConfig { fatalError("unused") }
    func updateAutoLinkConfig(_ autoLink: KGAutoLinkConfig) async throws -> KGUserConfig { fatalError("unused") }
    func deleteAccount() async throws { fatalError("unused") }
    func pullGraphLinks() async throws -> [KGGraphLink] { fatalError("unused") }
    func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink {
        fatalError("unused")
    }
    func deleteLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
    func hideLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
    func unhideLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
    func deleteCard(word: String, notebookId: String) async throws { fatalError("unused") }
    func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse {
        fatalError("unused")
    }
    func batchArchiveCards(words: [String], archived: Bool, notebookId: String) async throws -> KGBatchArchiveResponse {
        fatalError("unused")
    }
    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) { fatalError("unused") }
    func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int) { fatalError("unused") }
    func pullReviewEvents(container: ModelContainer) async throws { fatalError("unused") }
    func pushReviewQuietly(container: ModelContainer) async {}
    func clearLocalData(container: ModelContainer, reason: String) async {}
    func fetchQuota() async {}
    func pullCopiedDeck(container: ModelContainer, notebookId: String) async {}
}
#endif
