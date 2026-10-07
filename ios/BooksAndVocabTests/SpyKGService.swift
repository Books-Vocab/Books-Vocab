#if os(iOS)
import Foundation
import SwiftData
@testable import BooksAndVocab

/// 共用的 `KGServing` 測試替身。
///
/// 既有慣例是每個測試檔各自寫一份 42 個成員的 `private final class StubKGService`
/// （見 `PodcastPlayerLoaderTests` / `SettingsCoordinatorReviewClockTests`）。第四份
/// 手抄本沒有意義，故此處抽成共用替身：被測方法由**可注入的 handler** 決定行為，其餘
/// 不提供未使用的能力，讓測試替身與實際 consumer 契約保持最小。
///
/// 例外（沿用既有 stub 慣例，回傳無害值而非 trap）：`backgroundSync` / `healthCheck` /
/// `currentAuthToken` / `pushReviewQuietly` / `clearLocalData` / `fetchQuota` /
/// `pullCopiedDeck`。這幾個是背景雜訊型呼叫，trap 它們會讓無關測試炸開。
///
/// 關鍵設計：handler 讓替身能**模擬失敗**。若替身只會成功，rollback 這條失效路徑
/// 就從模型裡消失了，測試會對它永遠綠燈。
///
/// **必須是 `@MainActor`（#2166）**：handler 會在 in-flight 期間改動 `@Model` 實體（模擬背景
/// pull）。非隔離的 `async` 方法從 `@MainActor` 呼叫端呼叫時（Swift 5 mode）會跳到 global
/// executor，handler 就在 cooperative pool 的執行緒上寫 SwiftData 物件，同時別的測試在 main
/// thread 建立 `VocabularyEntry`——SwiftData 的 temporary identifier 註冊表因此偶發
/// `Already have an objectID registered` trap。隔離到 MainActor 後方法直接在呼叫端執行緒內跑完。
@MainActor
final class SpyKGService: CardArchiving {

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

}
#endif
