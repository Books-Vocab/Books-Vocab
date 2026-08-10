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
