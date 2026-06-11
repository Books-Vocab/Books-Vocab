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

struct PipelineStep: Identifiable {
    let id: String
    let label: String
    var status: StepStatus = .waiting
    var current: Int = 0
    var total: Int = 0
    var detail: String = ""
    var startTime: Date?
    var endTime: Date?

    enum StepStatus {
        case waiting
        case running
        case retry
        case done
        case skipped
        case error
    }
}

enum SyncPhase {
    case ready
    case running
    case completed
    case failed
}

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
        let syncStartTime = Date()

        pipelineTask = Task { [weak self] in
            defer { self?.pipelineTask = nil }
            guard let self else { return }
            // 部分失敗旗標宣告於 do/catch 之外:success path(do 內)與
            // cancel/error path(catch 內)的 syncTerminalOutcome 都要讀它,
            // 宣告在 do block 內會讓 catch 的 call site out of scope。
            var encounteredFailure = false
            do {
                // Defense-in-depth Layer 2: sanitize outbox before grouping by notebook.
                // 把指向已刪 notebook 的孤兒 entry 自動 reassign 到 default。
                // 同時是歷史 orphan 的 in-place migration — idempotent，重複跑無副作用。
                let sanitizedDeletedEntryIds = Self.sanitizeOutbox(
                    pendingEntries: pendingEntries,
                    modelContext: modelContext
                )

                // Tombstone defense: sanitize 對 orphan-delete 走 modelContext.delete()，
                // 但舊物件引用上的 PersistentModel.isDeleted 不可作為 save 後契約。
                // downstream filters 用 sanitize 本輪回傳的 stable entry ids 排除幽靈 entry。
                let deletes = pendingEntries.filter {
                    !sanitizedDeletedEntryIds.contains($0.id)
                        && $0.syncAction == .delete
                        && $0.shouldUploadOnNextSync
                }
                let adds = pendingEntries.filter {
                    !sanitizedDeletedEntryIds.contains($0.id)
                        && $0.syncAction == .add
                        && $0.shouldUploadOnNextSync
                }

                if !deletes.isEmpty {
                    self.updateStep("upload_delete", status: .running, total: deletes.count)
                    deletes.forEach { $0.prepareForRetryAttempt() }

                    // Group by notebook and batch-delete
                    let groupedDeletes = Dictionary(grouping: deletes, by: \.notebookId)
                    var deleted = 0
                    var failedWords: [String] = []

                    for (nbId, entries) in groupedDeletes {
                        if Task.isCancelled { break }
                        let words = entries.map(\.word)
                        do {
                            let response = try await kgService.batchDeleteCards(words: words, notebookId: nbId)
                            // Locally converge both server-deleted AND not_found words.
                            // not_found = 已不存在於 server，刪除意圖已達成，必須本地移除，
                            // 否則永遠 failed+delete → 每次 sync 回 not_found → 卡死。
                            let resolvableSet = Self.locallyResolvableDeletes(from: response)
                            for entry in entries {
                                if resolvableSet.contains(entry.word) {
                                    modelContext.delete(entry)
                                    deleted += 1
                                } else {
                                    entry.markSyncFailed()
                                    failedWords.append(entry.word)
                                }
                            }
                            self.updateStep("upload_delete", status: .running, current: deleted, total: deletes.count)
                        } catch {
                            // Batch failed — fallback to per-word delete
                            if Task.isCancelled { break }
                            for entry in entries {
                                if Task.isCancelled { break }
                                do {
                                    try await kgService.deleteCard(word: entry.word, notebookId: entry.notebookId)
                                    modelContext.delete(entry)
                                    deleted += 1
                                    self.updateStep("upload_delete", status: .running, current: deleted, total: deletes.count)
                                } catch {
                                    if Task.isCancelled { break }
                                    entry.markSyncFailed()
                                    encounteredFailure = true
                                    failedWords.append(entry.word)
                                }
                            }
                        }
                    }
                    if !failedWords.isEmpty { encounteredFailure = true }
                    modelContext.safeSave()

                    if failedWords.isEmpty {
                        self.updateStep(
                            "upload_delete",
                            status: .done,
                            current: deleted,
                            total: deleted,
                            detail: L10n.format("已刪除 %@ 個單字", "\(deleted)")
                        )
                    } else {
                        self.updateStep(
                            "upload_delete",
                            status: .error,
                            current: deleted,
                            total: deletes.count,
                            detail: L10n.format("部分失敗: %@", failedWords.joined(separator: ", "))
                        )
                    }
                }

                if !adds.isEmpty {
                    self.updateStep("upload_add", status: .running, total: adds.count)

                    let grouped = Dictionary(grouping: adds, by: \.notebookId)
                    var totalCreated = 0
                    var totalSkipped = 0
                    var batchFailed = false

                    for (nbId, entries) in grouped {
                        do {
                            entries.forEach { $0.prepareForRetryAttempt() }
                            let response = try await kgService.batchAdd(entries: entries, notebookId: nbId)

                            Self.convergeAddedEntries(response: response, entries: entries)
                            totalCreated += response.created
                            totalSkipped += response.skipped
                        } catch {
                            entries.forEach { $0.markSyncFailed() }
                            encounteredFailure = true
                            batchFailed = true
                        }
                    }
                    modelContext.safeSave()

                    if batchFailed {
                        let failedCount = adds.filter(\.isFailed).count
                        self.updateStep(
                            "upload_add",
                            status: .error,
                            current: adds.count - failedCount,
                            total: adds.count,
                            detail: L10n.format("部分上傳失敗（%@ 筆）", "\(failedCount)")
                        )
                    } else {
                        self.updateStep(
                            "upload_add",
                            status: .done,
                            current: adds.count,
                            total: adds.count,
                            detail: L10n.format("%@ 新增, %@ 已存在", "\(totalCreated)", "\(totalSkipped)")
                        )
                    }
                }

                // Defense-in-depth Layer 3: per-notebook trigger isolation.
                // 一個 notebook 的 trigger 失敗（例：notebook 已被刪 → 403）絕不能
                // 拖累其他 notebook 的 pipeline 觸發。今日事故的直接原因就是
                // `for nbId in notebookIds { try await ... }` 是 fail-fast，
                // 4205d6bed3ed 先 throw 後 default 的 trigger 永遠跑不到。
                // 委派 `triggerPipelinesIsolated` 讓測試與 production 共享同一份邏輯。
                self.updateStep("trigger", status: .running)
                let affectedNotebookIds = Set(adds.map(\.notebookId)).filter { !$0.isEmpty }
                let notebookIds = affectedNotebookIds.isEmpty
                    ? ["default"]
                    : affectedNotebookIds.sorted()  // deterministic order for log triage
                let triggerFailures = await Self.triggerPipelinesIsolated(
                    notebookIds: notebookIds
                ) { nbId in
                    try await kgService.triggerPipeline(notebookId: nbId)
                }
                if triggerFailures.isEmpty {
                    self.updateStep("trigger", status: .done, detail: L10n.string("已交由伺服器背景處理"))
                } else {
                    encounteredFailure = true
                    self.updateStep(
                        "trigger",
                        status: .error,
                        detail: L10n.format("部分通知失敗: %@", triggerFailures.joined(separator: ", "))
                    )
                }

                // Push review state + review events before pull
                self.updateStep("push_review", status: .running)
                do {
                    let result = try await kgService.pushReviewStates(container: modelContext.container)
                    _ = try await kgService.pushReviewEvents(container: modelContext.container)
                    self.updateStep("push_review", status: .done, detail: L10n.format("已同步 %@ 筆複習紀錄", "\(result.updated)"))
                } catch {
                    encounteredFailure = true
                    self.updateStep("push_review", status: .error, detail: error.localizedDescription)
                }

                self.updateStep("pull", status: .running, detail: L10n.string("正在下載單字..."))
                var pipelinePending = try await kgService.pullCardsToLocal(container: modelContext.container, progress: { [weak self] detail, current, total in
                    Task { @MainActor in
                        guard let self else { return }
                        // The progress closure fires off ordering-free unstructured
                        // Tasks; a stale lower `current` can land after a newer higher
                        // one and rewind the count (SyncPresenter animates `step.current`,
                        // making the regression a visible bounce-back). Drop any callback
                        // that would move this pull's count backward. The guard lives
                        // here — NOT in updateStep — because updateStep is shared by every
                        // step's start/reset/retry paths that legitimately set current=0.
                        if let idx = self.steps.firstIndex(where: { $0.id == "pull" }),
                           current < self.steps[idx].current {
                            return
                        }
                        self.updateStep("pull", status: .running, current: current, total: total, detail: detail)
                    }
                }, notebookId: nil)

                var retryCount = 0
                while pipelinePending && retryCount < 3 {
                    retryCount += 1
                    self.updateStep("pull", status: .running, detail: L10n.format("等待 AI 處理完成（%@/3）...", "\(retryCount)"))
                    try await Task.sleep(for: .seconds(10))
                    if Task.isCancelled { break }
                    pipelinePending = try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil, notebookId: nil)
                }

                // Also pull review events from server
                try await kgService.pullReviewEvents(container: modelContext.container)

                self.updateStep("pull", status: .done, current: 1, total: 1, detail: L10n.string("本地單字已建立完成"))
                let syncDurationMs = Int(Date().timeIntervalSince(syncStartTime) * 1000)
                // cancel 可能讓 pipeline 走 break 正常結束(未拋)而落到這裡;
                // 若不守旗標,success path 會把 cancelSync() 設好的 .cancelled
                // 覆寫成 .partial/.completed。
                switch syncTerminalOutcome(
                    wasCancelled: self.wasCancelledByUser,
                    thrownError: false,
                    encounteredFailure: encounteredFailure
                ) {
                case .keepCancelled:
                    break  // cancelSync() 已設 .cancelled,不動
                case .partial:
                    self.summaryText = L10n.string("部分項目未成功同步，可直接再次重試。")
                    self.failureKind = .partial
                    self.phase = .failed
                    AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .partial))
                case .completed:
                    self.phase = .completed
                    await SyncPendingTip.syncCompleted.donate()
                    SyncPendingTip().invalidate(reason: .actionPerformed)
                    AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .success))
                case .fullFailure:
                    break  // success path 不會回 .fullFailure(thrownError=false)
                }
            } catch {
                let syncDurationMs = Int(Date().timeIntervalSince(syncStartTime) * 1000)
                // cancel 後下一個 try await 拋 CancellationError 會落到這裡。
                // 不守旗標就會把 .cancelled 覆寫成泛型 .full(CancellationError
                // 的 localizedDescription ≈「操作無法完成」,誤導使用者以為崩潰)。
                // 非 cancel 的真實錯誤 wasCancelledByUser==false → 正常進 .full。
                switch syncTerminalOutcome(
                    wasCancelled: self.wasCancelledByUser,
                    thrownError: true,
                    encounteredFailure: encounteredFailure
                ) {
                case .keepCancelled:
                    break  // cancelSync() 已設 .cancelled,不覆寫
                case .fullFailure:
                    self.summaryText = error.localizedDescription
                    self.failureKind = .full
                    self.phase = .failed
                    AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .failed))
                case .partial, .completed:
                    break  // catch path 一律回 .keepCancelled 或 .fullFailure
                }
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
