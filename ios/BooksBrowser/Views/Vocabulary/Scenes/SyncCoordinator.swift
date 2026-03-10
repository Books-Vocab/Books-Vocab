import Foundation
import SwiftData
import SwiftUI

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

@MainActor
final class SyncCoordinator: ObservableObject {
    @Published var steps: [PipelineStep] = []
    @Published var phase: SyncPhase = .ready
    @Published var summaryText: String = ""
    @Published var failureKind: SyncFailureKind?

    private var pipelineTask: Task<Void, Never>?

    func buildSteps(deleteCount: Int, addCount: Int) {
        var list: [PipelineStep] = []

        if deleteCount > 0 {
            list.append(PipelineStep(id: "upload_delete", label: "刪除 KG 單字"))
        }
        if addCount > 0 {
            list.append(PipelineStep(id: "upload_add", label: "上傳新單字"))
        }

        list.append(PipelineStep(id: "trigger", label: "觸發背景 AI 處理"))
        list.append(PipelineStep(id: "pull", label: "下載知識庫至本地"))

        steps = list
    }

    func startSync(
        pendingEntries: [VocabularyEntry],
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        phase = .running
        summaryText = ""
        failureKind = nil

        pipelineTask = Task {
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
                            modelContext.delete(entry)
                            deleted += 1
                            updateStep("upload_delete", status: .running, current: deleted, total: deletes.count)
                        } catch {
                            entry.markSyncFailed()
                            encounteredFailure = true
                            failedWords.append(entry.word)
                        }
                    }
                    try? modelContext.save()

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
                        try? modelContext.save()

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
                        try? modelContext.save()
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

                updateStep("pull", status: .running, detail: L10n.string("從遠端下載知識庫..."))
                try await kgService.pullCardsToLocal(container: modelContext.container) { [weak self] detail, current, total in
                    Task { @MainActor in
                        self?.updateStep("pull", status: .running, current: current, total: total, detail: detail)
                    }
                }

                updateStep("pull", status: .done, current: 1, total: 1, detail: L10n.string("本地知識庫已建立完成"))
                if encounteredFailure {
                    summaryText = L10n.string("部分項目未成功同步，可直接再次重試。")
                    failureKind = .partial
                    phase = .failed
                } else {
                    phase = .completed
                }
            } catch {
                summaryText = error.localizedDescription
                failureKind = .full
                phase = .failed
            }
        }
    }

    func cancelSync() {
        pipelineTask?.cancel()
        pipelineTask = nil
        phase = .failed
        failureKind = .cancelled
        summaryText = L10n.string("同步已取消")
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
                }
            }
        }
    }
}
