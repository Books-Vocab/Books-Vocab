import Foundation
import SwiftData
import SwiftUI

@MainActor protocol KGVocabCoordinating: AnyObject, Observable {
    var isLoading: Bool { get }
    var errorMessage: String? { get }
    var selectedEntry: VocabularyEntry? { get set }
    func dismissBanner()
    func handleRowTap(_ entryID: UUID, syncedEntries: [VocabularyEntry])
    func handleDeleteTap(_ entryID: UUID, syncedEntries: [VocabularyEntry], modelContext: ModelContext, toastCoordinator: AppToastCoordinator)
    func loadInitialData(authManager: any AuthManaging, kgService: any KGServing, modelContext: ModelContext) async
    func forceRefresh(kgService: any KGServing, modelContext: ModelContext) async
    func retryPendingDeletes(pendingDeletes: [VocabularyEntry], kgService: any KGServing, modelContext: ModelContext) async
    func handleBatchDelete(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], modelContext: ModelContext, toastCoordinator: AppToastCoordinator)
    func handleBatchArchive(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], kgService: any KGServing, modelContext: ModelContext, toastCoordinator: AppToastCoordinator) async
}

@Observable @MainActor
final class KGVocabCoordinator: KGVocabCoordinating {
    var isLoading = false
    var errorMessage: String?
    var refreshSuccessMessage: String?
    var selectedEntry: VocabularyEntry?

    func dismissBanner() {
        errorMessage = nil
        refreshSuccessMessage = nil
    }

    func handleRowTap(_ entryID: UUID, syncedEntries: [VocabularyEntry]) {
        selectedEntry = syncedEntries.first { $0.id == entryID }
    }

    func handleDeleteTap(
        _ entryID: UUID,
        syncedEntries: [VocabularyEntry],
        modelContext: ModelContext,
        toastCoordinator: AppToastCoordinator
    ) {
        guard let entry = syncedEntries.first(where: { $0.id == entryID }) else { return }
        entry.queueDelete()
        if modelContext.safeSaveWithToast(toastCoordinator) {
            toastCoordinator.success("已刪除".localized)
        }
    }

    func loadInitialData(
        authManager: any AuthManaging,
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        guard authManager.isLoggedIn else { return }

        // Demo 模式已有本地資料，不需呼叫 API
        if authManager.isDemoMode { return }

        isLoading = true
        defer { isLoading = false }

        await pullAndApplyResult(kgService: kgService, modelContext: modelContext)
    }

    func forceRefresh(
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        isLoading = true
        defer { isLoading = false }

        async let health: Void = kgService.healthCheck()
        await pullAndApplyResult(kgService: kgService, modelContext: modelContext)
        await health
    }

    private func pullAndApplyResult(
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        do {
            try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil, notebookId: nil)
            errorMessage = nil
            refreshSuccessMessage = L10n.string("單字庫已更新")
        } catch {
            errorMessage = error.localizedDescription
            refreshSuccessMessage = nil
        }
    }

    func retryPendingDeletes(
        pendingDeletes: [VocabularyEntry],
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        var failedCount = 0
        let grouped = Dictionary(grouping: pendingDeletes, by: \.notebookId)

        for (nbId, entries) in grouped {
            let words = entries.map(\.word)
            do {
                let response = try await kgService.batchDeleteCards(words: words, notebookId: nbId)
                // not_found = 已不存在於 server → 刪除意圖已達成，與 deleted_words
                // 走同一條本地收斂路徑；否則該字永遠 failed+delete → 永久卡死重試。
                let resolvableSet = SyncCoordinator.locallyResolvableDeletes(from: response)
                for entry in entries {
                    if resolvableSet.contains(entry.word) {
                        modelContext.delete(entry)
                    } else {
                        failedCount += 1
                        AppLog.kg.error("batchDelete: word unresolved on server '\(entry.word)'")
                    }
                }
            } catch {
                // Fallback to per-word delete
                for entry in entries {
                    do {
                        try await kgService.deleteCard(word: entry.word, notebookId: entry.notebookId)
                        modelContext.delete(entry)
                    } catch {
                        failedCount += 1
                        AppLog.kg.error("deleteCard retry failed '\(entry.word)': \(error.localizedDescription)")
                    }
                }
            }
        }

        modelContext.safeSave()

        if failedCount > 0 {
            errorMessage = L10n.format("刪除失敗 %@ 筆，稍後將自動重試", "\(failedCount)")
        } else {
            // 全數收斂成功 → 清空前次失敗殘留的 error banner，
            // 對齊 loadInitialData / forceRefresh 成功路徑的清空慣例。
            errorMessage = nil
            refreshSuccessMessage = L10n.string("待刪除項目已同步")
        }

        await kgService.healthCheck()
    }

    func handleBatchDelete(
        _ entryIDs: Set<UUID>,
        syncedEntries: [VocabularyEntry],
        modelContext: ModelContext,
        toastCoordinator: AppToastCoordinator
    ) {
        let entries = syncedEntries.filter { entryIDs.contains($0.id) }
        for entry in entries {
            entry.queueDelete()
        }
        if modelContext.safeSaveWithToast(toastCoordinator) {
            toastCoordinator.success(L10n.format("已刪除 %@ 個", String(entries.count)))
        }
    }

    func handleBatchArchive(
        _ entryIDs: Set<UUID>,
        syncedEntries: [VocabularyEntry],
        kgService: any KGServing,
        modelContext: ModelContext,
        toastCoordinator: AppToastCoordinator
    ) async {
        let entries = syncedEntries.filter { entryIDs.contains($0.id) }
        var failCount = 0
        let grouped = Dictionary(grouping: entries, by: \.notebookId)

        for (nbId, nbEntries) in grouped {
            let words = nbEntries.map(\.word)
            do {
                let response = try await kgService.batchArchiveCards(words: words, archived: true, notebookId: nbId)
                let updatedSet = Self.locallyResolvableArchives(from: response)
                for entry in nbEntries {
                    if updatedSet.contains(entry.word) {
                        entry.isArchived = true
                    } else {
                        failCount += 1
                    }
                }
            } catch {
                // Fallback to per-word archive
                for entry in nbEntries {
                    do {
                        try await kgService.archiveCard(word: entry.word, archived: true, notebookId: entry.notebookId)
                        entry.isArchived = true
                    } catch {
                        failCount += 1
                        AppLog.kg.error("Batch archive failed '\(entry.word)': \(error.localizedDescription)")
                    }
                }
            }
        }
        if modelContext.safeSaveWithToast(toastCoordinator) {
            if failCount > 0 {
                let successCount = entries.count - failCount
                errorMessage = L10n.format("%@/%@ 張卡片已封存，部分失敗", "\(successCount)", "\(entries.count)")
            } else {
                // 全數封存成功 → 清空前次部分失敗殘留的 error banner，
                // 對齊 loadInitialData / forceRefresh 成功路徑的清空慣例。
                errorMessage = nil
                refreshSuccessMessage = L10n.string("封存已同步")
                toastCoordinator.success(L10n.format("已封存 %@ 個", String(entries.count)))
            }
        }
    }

    static func locallyResolvableArchives(
        from response: KGBatchArchiveResponse
    ) -> Set<String> {
        Set(response.updated_words).union(response.not_found)
    }

}
