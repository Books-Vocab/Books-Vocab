import Foundation
import SwiftData
import SwiftUI

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
        list.append(PipelineStep(id: "pull", label: "下載知識庫至本地".localized))

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

        pipelineTask = Task {
            defer { pipelineTask = nil }
            do {
                let deletes = pendingEntries.filter { $0.syncAction == .delete && $0.shouldUploadOnNextSync }
                let adds = pendingEntries.filter { $0.syncAction == .add && $0.shouldUploadOnNextSync }
                var encounteredFailure = false

                if !deletes.isEmpty {
                    updateStep("upload_delete", status: .running, total: deletes.count)

                    var deleted = 0
                    var failedWords: [String] = []
                    for entry in deletes {
                        if Task.isCancelled { break }
                        entry.prepareForRetryAttempt()
                        do {
                            try await kgService.deleteCard(word: entry.word)
                            if Task.isCancelled { break }
                            modelContext.delete(entry)
                            deleted += 1
                            updateStep("upload_delete", status: .running, current: deleted, total: deletes.count)
                        } catch {
                            if Task.isCancelled { break }
                            entry.markSyncFailed()
                            encounteredFailure = true
                            failedWords.append(entry.word)
                        }
                    }
                    modelContext.safeSave()

                    if failedWords.isEmpty {
                        updateStep(
                            "upload_delete",
                            status: .done,
                            current: deleted,
                            total: deleted,
                            detail: L10n.format("已刪除 %@ 個單字", "\(deleted)")
                        )
                    } else {
                        updateStep(
                            "upload_delete",
                            status: .error,
                            current: deleted,
                            total: deletes.count,
                            detail: L10n.format("部分失敗: %@", failedWords.joined(separator: ", "))
                        )
                    }
                }

                if !adds.isEmpty {
                    updateStep("upload_add", status: .running, total: adds.count)

                    do {
                        adds.forEach { $0.prepareForRetryAttempt() }
                        let response = try await kgService.batchAdd(entries: adds)

                        for entry in adds {
                            if let cardId = response.cardIds[entry.word] {
                                entry.kgCardId = cardId
                            }
                        }
                        modelContext.safeSave()

                        updateStep(
                            "upload_add",
                            status: .done,
                            current: adds.count,
                            total: adds.count,
                            detail: L10n.format("%@ 新增, %@ 已存在", "\(response.created)", "\(response.skipped)")
                        )
                    } catch {
                        adds.forEach { $0.markSyncFailed() }
                        encounteredFailure = true
                        modelContext.safeSave()
                        updateStep(
                            "upload_add",
                            status: .error,
                            current: 0,
                            total: adds.count,
                            detail: error.localizedDescription
                        )
                    }
                }

                updateStep("trigger", status: .running)
                do {
                    try await kgService.triggerPipeline()
                    updateStep("trigger", status: .done, detail: L10n.string("已交由伺服器背景處理"))
                } catch {
                    encounteredFailure = true
                    updateStep("trigger", status: .error, detail: L10n.format("無法觸發: %@", error.localizedDescription))
                }

                // Push review state + daily stats before pull
                updateStep("push_review", status: .running)
                do {
                    let result = try await kgService.pushReviewStates(container: modelContext.container)
                    _ = try? await kgService.pushDailyStats(container: modelContext.container)
                    updateStep("push_review", status: .done, detail: L10n.format("已同步 %@ 筆複習紀錄", "\(result.updated)"))
                } catch {
                    encounteredFailure = true
                    updateStep("push_review", status: .error, detail: error.localizedDescription)
                }

                updateStep("pull", status: .running, detail: L10n.string("從遠端下載知識庫..."))
                var pipelinePending = try await kgService.pullCardsToLocal(container: modelContext.container) { [weak self] detail, current, total in
                    Task { @MainActor in
                        self?.updateStep("pull", status: .running, current: current, total: total, detail: detail)
                    }
                }

                var retryCount = 0
                while pipelinePending && retryCount < 3 {
                    retryCount += 1
                    updateStep("pull", status: .running, detail: L10n.format("等待 AI 處理完成（%@/3）...", "\(retryCount)"))
                    try await Task.sleep(for: .seconds(10))
                    if Task.isCancelled { break }
                    pipelinePending = try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
                }

                // Also pull daily stats from server
                try? await kgService.pullDailyStats(container: modelContext.container)

                updateStep("pull", status: .done, current: 1, total: 1, detail: L10n.string("本地知識庫已建立完成"))
                let syncDurationMs = Int(Date().timeIntervalSince(syncStartTime) * 1000)
                if encounteredFailure {
                    summaryText = L10n.string("部分項目未成功同步，可直接再次重試。")
                    failureKind = .partial
                    phase = .failed
                    AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .partial))
                } else {
                    phase = .completed
                    AppAnalytics.track(.syncCompleted(durationMs: syncDurationMs, outcome: .success))
                }
            } catch {
                let syncDurationMs = Int(Date().timeIntervalSince(syncStartTime) * 1000)
                summaryText = error.localizedDescription
                failureKind = .full
                phase = .failed
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
