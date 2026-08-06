import Foundation
import SwiftData

/// 一次 `pullCardsToLocal` 的結果。
///
/// 取代原本的裸 `Bool`（只表達 pipeline pending），因為呼叫端需要區分的其實是兩件
/// 獨立的事：**伺服器還在算嗎**（決定要不要再輪詢）與 **本地單字庫真的變了嗎**
/// （決定要不要跟使用者說「已更新」）。裸 `Bool` 表達不了後者，於是 UI 只能無條件
/// 報「單字庫已更新」——每次進單字本都彈一次、即使那輪 merge 是 no-op。
struct KGPullOutcome: Sendable, Equatable {
    /// 伺服器 `X-Pipeline-Pending: true` — AI pipeline 仍在處理，值得稍後再拉一次。
    var pipelinePending: Bool
    /// 這輪 merge 實際新增的詞條數。
    var inserted: Int = 0
    /// 這輪 merge 實際更新（使用者可見內容真的不同）的詞條數；**不含複習狀態**。
    var updated: Int = 0
    /// 這輪 merge 實際刪除（remote soft-delete 或 orphan cleanup）的詞條數。
    var deleted: Int = 0

    /// 使用者可感知的變動筆數。
    var changedEntryCount: Int { inserted + updated + deleted }
    var hasChanges: Bool { changedEntryCount > 0 }

    static let unchanged = KGPullOutcome(pipelinePending: false)
}

/// 背景同步能力（窄協定）— 供顯式同步 UI（書架 pull-to-refresh / Mac toolbar /
/// ⌘R menu）依賴與 mock。比照 `LocalDataClearing` 的能力切分：consumer 只需這兩個
/// 成員，無謂背 `KGServing` 全表。`KGServing` 細化此協定，故 `any KGServing` 可直接
/// 傳入需要 `any BackgroundSyncing` 之處（existential upcast）。
protocol BackgroundSyncing: AnyObject {
    /// 最近一次背景同步失敗訊息（nil = 成功）。為跨 trigger 共享全域欄位，顯式同步
    /// consumer 須 read-then-clear（見 `ExplicitSync` / `BooksAndVocabApp` scenePhase）。
    var lastBackgroundSyncError: String? { get set }
    func backgroundSync(container: ModelContainer) async
    /// 逐步回報版本。`progress` 收到的事件描述「哪一步、走到哪」，供設定頁把單一
    /// 「同步中…」攤成逐步清單 + 進度條。
    ///
    /// 之所以是**額外一支**而不是給既有那支加參數：加參數會讓每個 mock 都得改
    /// 簽名，而它們一個都不關心進度。下面的預設實作把 reporter 丟掉並轉呼無參數
    /// 版，所以既有 conformance 零改動；只有真的會回報的 `KGService` 自己覆寫。
    ///
    /// 回傳 `SyncRoundOutcome` 是因為「這一輪發生了什麼」不能從
    /// `lastBackgroundSyncError` 讀——那是四個 trigger 共用的全域欄位，理由見該型別。
    @discardableResult
    func backgroundSync(container: ModelContainer, progress: SyncProgressReporting?) async -> SyncRoundOutcome
}

extension BackgroundSyncing {
    @discardableResult
    func backgroundSync(container: ModelContainer, progress: SyncProgressReporting?) async -> SyncRoundOutcome {
        await backgroundSync(container: container)
        return .completed
    }
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
protocol KGServing: BackgroundSyncing, DeckCopying, DictionaryServing {
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
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)?, notebookId: String?) async throws -> KGPullOutcome
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
    /// 複製成功後把新 notebook + 其卡片針對性拉回本地（複用既有 sync 基建）。自我
    /// 防禦、不 throw：pull 失敗僅記 log，卡片仍會在下次 backgroundSync 補齊。
    func pullCopiedDeck(container: ModelContainer, notebookId: String) async
}
