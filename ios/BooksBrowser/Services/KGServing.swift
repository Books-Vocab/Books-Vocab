import Foundation
import SwiftData

/// KGService 的行為契約
protocol KGServing: AnyObject {
    var serverURL: String { get set }
    var isConnected: Bool { get }
    var lastSyncDate: Date? { get }
    var serverCardCount: Int { get }
    var sessionExpiredReason: String? { get set }
    var lastBackgroundSyncError: String? { get set }

    func healthCheck() async
    func batchAdd(entries: [VocabularyEntry], notebookId: String) async throws -> KGAddResponse
    func triggerPipeline(notebookId: String) async throws
    @discardableResult
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)?, notebookId: String?) async throws -> Bool
    func fetchNotebooks() async throws -> [KGNotebook]
    func createNotebook(name: String, color: String?) async throws -> KGNotebook
    func updateNotebook(id: String, name: String?, color: String?) async throws -> KGNotebook
    func deleteNotebook(id: String) async throws
    func fetchUserConfig() async throws -> KGUserConfig
    func fetchEntitlements() async throws -> KGEntitlements
    func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements
    func updateOptionalIntegrationKey(_ apiKey: String) async throws -> KGUserConfig
    func updateTranslationConfig(_ translationConfig: KGTranslationConfig) async throws -> KGUserConfig
    func deleteAccount() async throws
    func pullGraphLinks() async throws -> [KGGraphLink]
    func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink
    func deleteLink(linkId: String, notebookId: String) async throws
    func deleteCard(word: String, notebookId: String) async throws
    func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse
    func archiveCard(word: String, archived: Bool, notebookId: String) async throws
    func batchArchiveCards(words: [String], archived: Bool, notebookId: String) async throws -> KGBatchArchiveResponse
    func moveCards(words: [String], fromNotebook: String, toNotebook: String) async throws
    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int)
    func pushDailyStats(container: ModelContainer) async throws -> Int
    func pullDailyStats(container: ModelContainer) async throws
    func backgroundSync(container: ModelContainer) async
    func pushReviewQuietly(container: ModelContainer) async
    func clearLocalData(container: ModelContainer, reason: String) async
}
