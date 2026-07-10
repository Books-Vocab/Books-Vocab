import Foundation
import SwiftData

/// 背景同步能力（窄協定）— 供顯式同步 UI（書架 pull-to-refresh / Mac toolbar /
/// ⌘R menu）依賴與 mock。比照 `LocalDataClearing` 的能力切分：consumer 只需這兩個
/// 成員，無謂背 `KGServing` 全表。`KGServing` 細化此協定，故 `any KGServing` 可直接
/// 傳入需要 `any BackgroundSyncing` 之處（existential upcast）。
protocol BackgroundSyncing: AnyObject {
    /// 最近一次背景同步失敗訊息（nil = 成功）。為跨 trigger 共享全域欄位，顯式同步
    /// consumer 須 read-then-clear（見 `ExplicitSync` / `BooksAndVocabApp` scenePhase）。
    var lastBackgroundSyncError: String? { get set }
    func backgroundSync(container: ModelContainer) async
}

/// 共享牌組複製能力（窄協定）— 供 Explore 複製流程（`SharedDeckCopyController`）依賴
/// 與 mock，比照 `BackgroundSyncing` 的能力切分。`KGServing` 細化此協定，故 `any
/// KGServing` 可直接當 `any DeckCopying` 傳入複製 controller。
protocol DeckCopying: AnyObject {
    /// `POST /api/decks/{deckId}/copy`（需登入 CurrentUser）。`idempotencyKey` 讓
    /// transport retry 安全 —— 同 key 永遠短路回同一 notebook，絕不重複複製。
    /// `notebookName` 非 nil 時覆寫 server 自動命名（server 仍保證與活躍 notebook 名唯一）。
    func copyDeck(deckId: String, idempotencyKey: String, notebookName: String?) async throws -> DeckCopyResponse
}

/// KGService 的行為契約
protocol KGServing: BackgroundSyncing, DeckCopying {
    var serverURL: String { get set }
    var isConnected: Bool { get }
    var lastSyncDate: Date? { get }
    var serverCardCount: Int { get }
    var sessionExpiredReason: String? { get set }

    func currentAuthToken() async throws -> String
    func healthCheck() async
    func batchAdd(entries: [VocabularyEntry], notebookId: String) async throws -> KGAddResponse
    func triggerPipeline(notebookId: String) async throws
    @discardableResult
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)?, notebookId: String?) async throws -> Bool
    func fetchNotebooks() async throws -> [KGNotebook]
    func createNotebook(name: String, color: String?, coverPattern: String?) async throws -> KGNotebook
    func updateNotebook(id: String, name: String?, color: String?, coverPattern: String?) async throws -> KGNotebook
    func deleteNotebook(id: String) async throws
    func fetchUserConfig() async throws -> KGUserConfig
    func fetchEntitlements() async throws -> KGEntitlements
    func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements
    func updateTranslationConfig(_ translationConfig: KGTranslationConfig) async throws -> KGUserConfig
    func updateReviewClockConfig(_ reviewClock: KGReviewClockConfig) async throws -> KGUserConfig
    func updateReviewModeConfig(_ reviewMode: KGReviewModeConfig) async throws -> KGUserConfig
    func updateVocabUIConfig(_ vocabUI: KGVocabUIConfig) async throws -> KGUserConfig
    func updateAutoLinkConfig(_ autoLink: KGAutoLinkConfig) async throws -> KGUserConfig
    func deleteAccount() async throws
    func pullGraphLinks() async throws -> [KGGraphLink]
    func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink
    func deleteLink(linkId: String, notebookId: String) async throws
    func hideLink(linkId: String, notebookId: String) async throws
    func unhideLink(linkId: String, notebookId: String) async throws
    func deleteCard(word: String, notebookId: String) async throws
    func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse
    func archiveCard(word: String, archived: Bool, notebookId: String) async throws
    func batchArchiveCards(words: [String], archived: Bool, notebookId: String) async throws -> KGBatchArchiveResponse
    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int)
    func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int)
    func pullReviewEvents(container: ModelContainer) async throws
    func pushReviewQuietly(container: ModelContainer) async
    func clearLocalData(container: ModelContainer, reason: String) async
    func fetchQuota() async
}
