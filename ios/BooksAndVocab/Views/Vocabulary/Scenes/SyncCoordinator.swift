import Foundation
import SwiftData
import SwiftUI
import TipKit

@MainActor protocol SyncCoordinating: AnyObject, Observable {
    var steps: [PipelineStep] { get }
    var phase: SyncPhase { get }
    var summaryText: String { get }
    var failureKind: SyncFailureKind? { get }
    func buildSteps(deleteCount: Int, addCount: Int)
    func startSync(pendingEntries: [VocabularyEntry], modelContext: ModelContext, kgService: any KGServing)
    func cancelSync()
    func resetForRetry(deleteCount: Int, addCount: Int)
}

// `PipelineStep` / `SyncPhase` 已搬到 `Services/SyncProgress.swift`——設定頁的
// 逐步同步進度共用同一組型別與同一套呈現，不該為此 import 詞庫頁這條管線。

enum SyncFailureKind {
    case partial
    case full
    case cancelled
}

/// Pipeline 跑完(或拋錯)後該落入的終態。
///
/// 抽成純函式讓「cancel 後不被泛型全失敗覆寫」的關鍵分類邏輯可單元測試,
/// 不必拖整條真實 async pipeline。三個輸入完全決定終態:
/// - `wasCancelled`：使用者已按取消(`cancelSync()` 設旗標)。**最高優先級** —
///   cancel 後無論 pipeline 走 break 正常結束、或某 `try await` 拋 `CancellationError`,
///   都不可覆寫 `cancelSync()` 已設好的 `.cancelled` 終態。回 `nil` 代表「保持現狀,
///   呼叫端不要動 phase/failureKind/summary」。
/// - `thrownError`：catch 收到的 error。非 nil = 走了 catch path。
/// - `encounteredFailure`：success path 累積的部分失敗旗標。
enum SyncTerminalOutcome: Equatable {
    /// 維持 `cancelSync()` 已設的 `.cancelled` 終態,呼叫端不覆寫。
    case keepCancelled
    /// `.completed` 全綠。
    case completed
    /// `.failed` + `.partial`,部分項目未同步。
    case partial
    /// `.failed` + `.full`,整條 pipeline 拋錯。
    case fullFailure
}

/// 等待伺服器 AI pipeline 收尾的重試間隔（秒），前密後疏。
///
/// 舊版是固定 10s × 3。pipeline 多數時候在數秒內就好了,固定 10s 代表**已經好了
/// 也要再等滿 10 秒**才會看到——使用者感受到的「Pending 很久」有一大半是這段空等,
/// 不是伺服器真的還在算。前密後疏讓常見的快路徑 1 秒就收斂,慢路徑仍有 15s 總預算
/// (舊版 30s)可等。
let syncPipelinePendingBackoffSeconds: [Double] = [1, 2, 4, 8]

/// 純函式:由三個訊號決定 sync 終態。見 `SyncTerminalOutcome`。
/// `wasCancelled` 一律壓過其他訊號(含 catch path 拋的 `CancellationError`)。
func syncTerminalOutcome(
    wasCancelled: Bool,
    thrownError: Bool,
    encounteredFailure: Bool
) -> SyncTerminalOutcome {
    if wasCancelled { return .keepCancelled }
    if thrownError { return .fullFailure }
    return encounteredFailure ? .partial : .completed
}

@Observable @MainActor
final class SyncCoordinator: SyncCoordinating {
    var steps: [PipelineStep] = []
    var phase: SyncPhase = .ready
    var summaryText: String = ""
    var failureKind: SyncFailureKind?

    @ObservationIgnored private var pipelineTask: Task<Void, Never>?
    /// 使用者已按取消。`cancelSync()` 已搶先把終態設成 `.cancelled`;pipeline
    /// 收尾(success path 或 catch path)看到此旗標就不覆寫終態。
    /// `Task.isCancelled` 不夠用——非 cancel 的真實錯誤也可能在 cancel 之外發生,
    /// 而此旗標只在使用者主動取消時為 true。
    @ObservationIgnored private var wasCancelledByUser = false

    func buildSteps(deleteCount: Int, addCount: Int) {
        var list: [PipelineStep] = []

        if deleteCount > 0 {
            list.append(PipelineStep(id: "upload_delete", label: "刪除 Books & Vocab 單字".localized))
        }
        if addCount > 0 {
            list.append(PipelineStep(id: "upload_add", label: "上傳新單字".localized))
        }

        list.append(PipelineStep(id: "trigger", label: "觸發背景 AI 處理".localized))
        list.append(PipelineStep(id: "push_review", label: "上傳複習進度".localized))
        list.append(PipelineStep(id: "pull", label: "下載單字至本地".localized))

        steps = list
    }

    func startSync(
        pendingEntries: [VocabularyEntry],
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard phase != .running else { return }
        phase = .running
        summaryText = ""
        failureKind = nil
        wasCancelledByUser = false
        AppAnalytics.track(.syncStarted)

        let adapter = KGServingVocabularySyncAdapter(base: kgService)
        let executor: any VocabularySyncExecuting = VocabularySyncEngine()
        pipelineTask = Task { [weak self] in
            defer { self?.pipelineTask = nil }
            guard let self else { return }

            let result = await executor.execute(
                pendingEntries: pendingEntries,
                modelContext: modelContext,
                service: adapter,
                emit: { [weak self] event in
                    self?.project(event)
                }
            )

            switch result.terminalOutcome {
            case .keepCancelled:
                break
            case .partial:
                self.summaryText = L10n.string("部分項目未成功同步，可直接再次重試。")
                self.failureKind = .partial
                self.phase = .failed
                AppAnalytics.track(.syncCompleted(durationMs: result.durationMs, outcome: .partial))
            case .completed:
                self.phase = .completed
                await SyncPendingTip.syncCompleted.donate()
                SyncPendingTip().invalidate(reason: .actionPerformed)
                AppAnalytics.track(.syncCompleted(durationMs: result.durationMs, outcome: .success))
            case .fullFailure:
                self.failureKind = .full
                self.phase = .failed
                AppAnalytics.track(.syncCompleted(durationMs: result.durationMs, outcome: .failed))
            }
        }
    }

    func cancelSync() {
        wasCancelledByUser = true
        pipelineTask?.cancel()
        phase = .failed
        failureKind = .cancelled
        summaryText = L10n.string("同步已取消")
        AppAnalytics.track(.syncCompleted(durationMs: 0, outcome: .cancelled))
    }

    func resetForRetry(deleteCount: Int, addCount: Int) {
        buildSteps(deleteCount: deleteCount, addCount: addCount)
        phase = .ready
        summaryText = ""
        failureKind = nil
    }

    /// 把 outbox 內指向已刪 / 不存在 notebook 的孤兒 entry 修好。
    ///
    /// - **Pending add orphan** → reassign to "default"，下次 sync 用 default 上傳
    /// - **Pending delete orphan** → local hard-delete（不送 server）。理由：
    ///   server 端 cascade 已經把該 notebook 下所有 card 刪掉了，繼續對 server
    ///   發 delete 不只多餘，rewrite 到 default 還可能誤刪 default 內同名字（同
    ///   `word` 但 cardId 不同），破壞使用者資料。
    /// - 同時是歷史 orphan 的 in-place migration，無需獨立 launch-time script
    /// - Idempotent — 重複跑無副作用，已是 default 或已 valid 的 entry 完全不變
    /// - 在 sync 入口呼叫一次，把 race condition 的後果在落 server 之前修好
    @discardableResult
    static func sanitizeOutbox(
        pendingEntries: [VocabularyEntry],
        modelContext: ModelContext
    ) -> Set<UUID> {
        var sanitized = 0
        var deletedEntryIds: Set<UUID> = []
        for entry in pendingEntries where entry.shouldUploadOnNextSync {
            let resolved = VocabularyEntry.resolveNotebookId(entry.notebookId, in: modelContext)
            guard resolved != entry.notebookId else { continue }
            if entry.syncAction == .delete {
                // 孤兒 delete：server 已 cascade 過，rewrite 到 default 風險大於收益
                AppLog.kg.warning("drop orphan delete: \(entry.word) from \(entry.notebookId)")
                deletedEntryIds.insert(entry.id)
                modelContext.delete(entry)
            } else {
                AppLog.kg.warning("sanitize orphan add: \(entry.word) \(entry.notebookId) → \(resolved)")
                entry.notebookId = resolved
            }
            sanitized += 1
        }
        if sanitized > 0 {
            modelContext.safeSave()
        }
        return deletedEntryIds
    }

    /// Batch-delete 回應中「可在本地安全收斂(刪除)」的字集合。
    ///
    /// = `deleted_words ∪ not_found`。兩者都是 happy-path:
    /// - `deleted_words`：server 這次成功刪掉的字。
    /// - `not_found`：server 上本就不存在的字（前一次已刪 / race）。對本地而言
    ///   刪除意圖已達成，必須同樣本地移除，否則該 entry 永遠標 `failed+delete`
    ///   → 每次 sync server 都回 `not_found` → 永久卡死的隱形重試迴圈。
    ///
    /// 只有「既不在 deleted_words 也不在 not_found」的字才是真正的 server 異常，
    /// 應 `markSyncFailed()` 重試。Set union 自然去重（兩集合理論上不重疊，但不依賴此前提）。
    static func locallyResolvableDeletes(
        from response: KGBatchDeleteResponse
    ) -> Set<String> {
        Set(response.deleted_words).union(response.not_found)
    }

    /// startSync batch-delete happy path 的回應分類收斂。抽成 static 函式讓
    /// 測試與 production 共用同一份邏輯（消除測試手抄 mirror loop 的
    /// dead-test 風險，比照 `triggerPipelinesIsolated`）。
    ///
    /// 本地收斂集合 = `deleted_words ∪ not_found`（`locallyResolvableDeletes`）：
    /// not_found = 已不存在於 server，刪除意圖已達成，必須本地移除，否則
    /// 永遠 failed+delete → 每次 sync 回 not_found → 卡死的隱形重試迴圈。
    /// 不在集合內（含 `failed` bucket = server graph 操作已回滾、卡片仍在）
    /// → markSyncFailed 保留重試（sync_lifecycle.md 不變式 1/2，#720）。
    static func applyBatchDeleteResponse(
        response: KGBatchDeleteResponse,
        entries: [VocabularyEntry],
        modelContext: ModelContext
    ) -> (deleted: Int, failedWords: [String]) {
        let resolvableSet = locallyResolvableDeletes(from: response)
        var deleted = 0
        var failedWords: [String] = []
        for entry in entries {
            if resolvableSet.contains(entry.word) {
                modelContext.delete(entry)
                deleted += 1
            } else {
                entry.markSyncFailed()
                failedWords.append(entry.word)
            }
        }
        return (deleted, failedWords)
    }

    /// 依 `cardRole` 把 outbox 內的 pending delete 切成兩條互斥路徑。
    ///
    /// Reader / PDF / 詞庫列表的「移除」一律只做 `queueDelete()`，把實際
    /// 傳輸交給這條 outbox drain — 也就是說 drain 是唯一知道「這張卡該打哪個
    /// endpoint」的地方。Legacy 的 `batchDeleteCards` / `deleteCard` 以
    /// `(word, notebookId)` 定位卡片，對字典卡是錯的路徑：它不會做 graph link
    /// rollback、不碰 archive refcount，刪完 server 上還留著指向已刪節點的邊。
    /// 字典卡必須走 `deleteDictionaryCard(cardId:notebookId:)`。
    ///
    /// 分流只看 `cardRole`，不看 `kgCardId` — 沒有 cardId 的字典卡代表從未上傳，
    /// 由 `drainDictionaryDeletes` 就地本地收斂，不該偷渡回 legacy 路徑。
    nonisolated static func partitionDeletesByRole(
        _ entries: [VocabularyEntry]
    ) -> (learning: [VocabularyEntry], dictionary: [VocabularyEntry]) {
        var learning: [VocabularyEntry] = []
        var dictionary: [VocabularyEntry] = []
        for entry in entries {
            if entry.cardRole == .dictionary {
                dictionary.append(entry)
            } else {
                learning.append(entry)
            }
        }
        return (learning, dictionary)
    }

    /// 排掉字典卡的 pending delete。抽成 static 讓測試與 production 共用同一份
    /// 邏輯（比照 `applyBatchDeleteResponse` / `triggerPipelinesIsolated`）。
    ///
    /// - server 回的 tombstone 必須 `isDeleted == true` 才算成功；否則視為失敗
    ///   保留重試，不可只因 HTTP 200 就本地收斂。
    /// - 成功才做本地收斂：移除 entry **並**把 peer 上指向該 cardId 的 link
    ///   summary 一併清掉（server 端 rollback 的本地鏡像）。失敗是 no-op —
    ///   entry 與 link 都留著，否則一次網路錯誤就讓本地與 server 永久分岔。
    /// - 沒有 `kgCardId` = 從未上傳，server 無物可刪，直接本地收斂。
    @discardableResult
    static func drainDictionaryDeletes(
        _ entries: [VocabularyEntry],
        peers: [VocabularyEntry],
        modelContext: ModelContext,
        delete: (_ cardID: String, _ notebookID: String) async throws -> KGCard
    ) async -> (deleted: Int, failedWords: [String]) {
        var deleted = 0
        var failedWords: [String] = []
        for entry in entries {
            if Task.isCancelled { break }
            guard let cardID = entry.kgCardId, !cardID.isEmpty else {
                modelContext.delete(entry)
                deleted += 1
                continue
            }
            do {
                let tombstone = try await delete(cardID, entry.notebookId)
                guard tombstone.isDeleted == true else {
                    throw KGError.serverError("Dictionary delete response was not a tombstone")
                }
                purgeGraphLinks(toCardID: cardID, in: peers)
                modelContext.delete(entry)
                deleted += 1
            } catch {
                if Task.isCancelled { break }
                entry.markSyncFailed()
                failedWords.append(entry.word)
            }
        }
        return (deleted, failedWords)
    }

    /// 本地 graph rollback：把所有 peer 上指向 `cardID` 的 link summary 移除，
    /// 空掉的 kind group 一併收掉（比照 `VocabularyEntry.mutateLink` 的收斂）。
    static func purgeGraphLinks(toCardID cardID: String, in entries: [VocabularyEntry]) {
        for entry in entries {
            var groups = entry.graphLinksByKind
            var changed = false
            for (kind, links) in groups {
                let remaining = links.filter { $0.cardId != cardID }
                guard remaining.count != links.count else { continue }
                changed = true
                groups[kind] = remaining.isEmpty ? nil : remaining
            }
            if changed { entry.graphLinksByKind = groups }
        }
    }

    /// startSync add-path 的 batchAdd 回應收斂。抽成 static 純函式讓測試與
    /// production 共用同一份邏輯（比照 `locallyResolvableDeletes`）。
    ///
    /// 後端以『原始』submitted word 為 cardIds key（created 與 duplicate 皆
    /// 回填 id），故 `entry.word` byte-exact 配對必中（sync_lifecycle.md
    /// 不變式 6）。回傳 cardId = 卡片確實存在 server（權威確認）→ 直接
    /// markSynced 出列，不再依賴 pull-merge 用 content 比對（會被後端清洗
    /// strip 尾標點/首字小寫破壞，例 "chateau," 永遠對不上 "chateau" →
    /// 卡在佇列重送）。無 cardId（異常）才保持 pending，下次重試。
    ///
    /// 回傳未收斂的 entries（正常情況為空）供觀測；呼叫端不需特別處理，
    /// 它們維持 pending+add 自然進下一輪。
    @discardableResult
    static func convergeAddedEntries(
        response: KGAddResponse,
        entries: [VocabularyEntry]
    ) -> [VocabularyEntry] {
        var unresolved: [VocabularyEntry] = []
        for entry in entries {
            if let cardId = response.cardIds[entry.word] {
                entry.kgCardId = cardId
                entry.markSynced()
            } else {
                unresolved.append(entry)
            }
        }
        return unresolved
    }

    /// Per-notebook isolated trigger pipeline 呼叫迴圈。
    ///
    /// 抽出來讓 `SyncCoordinator.startSync` 與測試共享同一份 isolation 邏輯，
    /// 避免「測試裡寫的 pattern」與「production 跑的 pattern」分裂的 dead-test 問題。
    /// 任何單一 notebook 失敗（例：notebook 已被刪 → 403）絕不會中斷其他 notebook 的觸發。
    /// 回傳失敗的 notebook id 列表（成功時為空）。
    static func triggerPipelinesIsolated(
        notebookIds: [String],
        trigger: (String) async throws -> Void
    ) async -> [String] {
        var failures: [String] = []
        for nbId in notebookIds {
            if Task.isCancelled { break }
            do {
                try await trigger(nbId)
            } catch {
                failures.append(nbId)
                AppLog.kg.error("triggerPipeline(\(nbId)) failed: \(error.localizedDescription)")
            }
        }
        return failures
    }

    private func project(_ event: VocabularySyncEvent) {
        switch event {
        case .stepStarted(let id):
            updateStep(id, status: .running)
        case .stepProgress(let id, let current, let total, let detail):
            updateStep(id, status: .running, current: current, total: total, detail: detail)
        case .stepFinished(let id, let status, let detail):
            updateStep(id, status: status, detail: detail)
        }
    }

    private func updateStep(
        _ id: String,
        status: PipelineStep.StepStatus,
        current: Int = 0,
        total: Int = 0,
        detail: String = ""
    ) {
        guard let idx = steps.firstIndex(where: { $0.id == id }) else { return }

        withAnimation(AppMotion.phaseChange) {
            steps[idx].status = status
            steps[idx].current = current
            steps[idx].total = total
            if !detail.isEmpty {
                steps[idx].detail = detail
            }

            if status == .running && steps[idx].startTime == nil {
                steps[idx].startTime = Date()
            }
            if status == .done || status == .skipped || status == .error {
                if steps[idx].endTime == nil {
                    steps[idx].endTime = Date()
                    let durationMs = steps[idx].startTime.map {
                        Int(Date().timeIntervalSince($0) * 1000)
                    } ?? 0
                    AppAnalytics.track(.syncStepCompleted(
                        step: id,
                        durationMs: durationMs,
                        success: status == .done || status == .skipped
                    ))
                }
            }
        }
    }
}
