import Foundation
import SwiftData

/// KGService 的行為契約
protocol KGServing: AnyObject {
    var serverURL: String { get set }
    var isConnected: Bool { get }
    var lastSyncDate: Date? { get }
    var serverCardCount: Int { get }

    func healthCheck() async
    func batchAdd(entries: [VocabularyEntry]) async throws -> KGAddResponse
    func triggerPipeline() async throws
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)?) async throws
    func fetchUserConfig() async throws -> KGUserConfig
    func fetchEntitlements() async throws -> KGEntitlements
    func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements
    func updateUserConfig(optionalIntegrationKey: String?) async throws -> KGUserConfig
    func deleteAccount() async throws
    func pullGraphLinks() async throws -> [KGGraphLink]
    func deleteCard(word: String) async throws
    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int)
    func clearLocalData(container: ModelContainer, reason: String) async
}
