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

@Observable @MainActor
final class SyncCoordinator: SyncCoordinating {
    var steps: [PipelineStep] = []
    var phase: SyncPhase = .ready
    var summaryText: String = ""
    var failureKind: SyncFailureKind?

    @ObservationIgnored private var pipelineTask: Task<Void, Never>?

    func buildSteps(deleteCount: Int, addCount: Int) {
        var list: [PipelineStep] = []

        if deleteCount > 0 {
            list.append(PipelineStep(id: "upload_delete", label: "刪除 KG 單字".localized))
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
        AppAnalytics.track(.syncStarted)
        let syncStartTime = Date()

        pipelineTask = Task { [weak self] in
            defer { self?.pipelineTask = nil }
            guard let self else { return }
            do {
                let deletes = pendingEntries.filter { $0.syncAction == .delete && $0.shouldUploadOnNextSync }
                let adds = pendingEntries.filter { $0.syncAction == .add && $0.shouldUploadOnNextSync }
                var encounteredFailure = false

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
                            // Delete locally for successfully deleted words
                            let deletedSet = Set(response.deleted_words)
                            for entry in entries {
                                if deletedSet.contains(entry.word) {
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

                            for entry in entries {
                                if let cardId = response.cardIds[entry.word] {
                                    entry.kgCardId = cardId
                                }
                            }
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

                self.updateStep("trigger", status: .running)
                do {
                    let affectedNotebookIds = Set(adds.map(\.notebookId)).filter { !$0.isEmpty }
                    let notebookIds = affectedNotebookIds.isEmpty ? ["default"] : Array(affectedNotebookIds)
                    for nbId in notebookIds {
                        try await kgService.triggerPipeline(notebookId: nbId)
                    }
                    self.updateStep("trigger", status: .done, detail: L10n.string("已交由伺服器背景處理"))
                } catch {
                    encounteredFailure = true
                    self.updateStep("trigger", status: .error, detail: L10n.format("無法觸發: %@", error.localizedDescription))
                }

                // Push review state + daily stats before pull
                self.updateStep("push_review", status: .running)
                do {
                    let result = try await kgService.pushReviewStates(container: modelContext.container)
                    _ = try? await kgService.pushDailyStats(container: modelContext.container)
                    self.updateStep("push_review", status: .done, detail: L10n.format("已同步 %@ 筆複習紀錄", "\(result.updated)"))
                } catch {
                    encounteredFailure = true
                    self.updateStep("push_review", status: .error, detail: error.localizedDescription)
                }

                self.updateStep("pull", status: .running, detail: L10n.string("正在下載單字..."))
                var pipelinePending = try await kgService.pullCardsToLocal(container: modelContext.container, progress: { [weak self] detail, current, total in
                    Task { @MainActor in
                        self?.updateStep("pull", status: .running, current: current, total: total, detail: detail)
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

                // Also pull daily stats from server
                try? await kgService.pullDailyStats(container: modelContext.container)

                self.updateStep("pull", status: .done, current: 1, total: 1, detail: L10n.string("本地單字已建立完成"))
                let syncDurationMs = Int(Date().timeIntervalSince(syncStartTime) * 1000)
                if encounteredFailure {
                    self.summaryText = L10n.string("部分項目未成功同步，可直接再次重試。")
                    self.failureKind = .partial
                    self.phase = .failed
                    AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .partial))
                } else {
                    self.phase = .completed
                    await SyncPendingTip.syncCompleted.donate()
                    SyncPendingTip().invalidate(reason: .actionPerformed)
                    AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .success))
                }
            } catch {
                let syncDurationMs = Int(Date().timeIntervalSince(syncStartTime) * 1000)
                self.summaryText = error.localizedDescription
                self.failureKind = .full
                self.phase = .failed
                AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .failed))
            }
        }
    }

    func cancelSync() {
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
