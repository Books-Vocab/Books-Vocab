import Foundation
import SwiftData
import SwiftUI

@MainActor protocol KGVocabCoordinating: AnyObject, Observable {
    var isLoading: Bool { get }
    var errorMessage: String? { get }
    var selectedEntry: VocabularyEntry? { get set }
    func dismissBanner()
    func handleRowTap(_ entryID: UUID, syncedEntries: [VocabularyEntry])
    func handleDeleteTap(_ entryID: UUID, syncedEntries: [VocabularyEntry], modelContext: ModelContext)
    func loadInitialData(authManager: any AuthManaging, kgService: any KGServing, modelContext: ModelContext, dueEntries: [VocabularyEntry], unlearnedEntries: [VocabularyEntry], selectedReviewState: Binding<VocabularyReviewState>) async
    func forceRefresh(kgService: any KGServing, modelContext: ModelContext) async
    func retryPendingDeletes(pendingDeletes: [VocabularyEntry], kgService: any KGServing, modelContext: ModelContext) async
    func handleBatchDelete(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], modelContext: ModelContext)
    func handleBatchArchive(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], kgService: any KGServing, modelContext: ModelContext) async
    func handleBatchMove(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], toNotebook: String, fromNotebook: String, kgService: any KGServing, modelContext: ModelContext) async throws
}

@Observable @MainActor
final class KGVocabCoordinator: KGVocabCoordinating {
    var isLoading = false
    var errorMessage: String?
    var selectedEntry: VocabularyEntry?

    func dismissBanner() {
        errorMessage = nil
    }

    func handleRowTap(_ entryID: UUID, syncedEntries: [VocabularyEntry]) {
        selectedEntry = syncedEntries.first { $0.id == entryID }
    }

    func handleDeleteTap(
        _ entryID: UUID,
        syncedEntries: [VocabularyEntry],
        modelContext: ModelContext
    ) {
        guard let entry = syncedEntries.first(where: { $0.id == entryID }) else { return }
        entry.queueDelete()
        modelContext.safeSave()
    }

    func loadInitialData(
        authManager: any AuthManaging,
        kgService: any KGServing,
        modelContext: ModelContext,
        dueEntries: [VocabularyEntry],
        unlearnedEntries: [VocabularyEntry],
        selectedReviewState: Binding<VocabularyReviewState>
    ) async {
        guard authManager.isLoggedIn else { return }

        // Demo 模式已有本地資料，不需呼叫 API
        if authManager.isDemoMode {
            if dueEntries.isEmpty && !unlearnedEntries.isEmpty {
                selectedReviewState.wrappedValue = .unlearned
            }
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil, notebookId: nil)
            errorMessage = nil
            if dueEntries.isEmpty && !unlearnedEntries.isEmpty {
                selectedReviewState.wrappedValue = .unlearned
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func forceRefresh(
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        async let health: Void = kgService.healthCheck()
        do {
            try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil, notebookId: nil)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        await health
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
                let deletedSet = Set(response.deleted_words)
                for entry in entries {
                    if deletedSet.contains(entry.word) {
                        modelContext.delete(entry)
                    } else {
                        failedCount += 1
                        AppLog.kg.error("batchDelete: word not found '\(entry.word)'")
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
        }

        await kgService.healthCheck()
    }

    func handleBatchDelete(
        _ entryIDs: Set<UUID>,
        syncedEntries: [VocabularyEntry],
        modelContext: ModelContext
    ) {
        let entries = syncedEntries.filter { entryIDs.contains($0.id) }
        for entry in entries {
            entry.queueDelete()
        }
        modelContext.safeSave()
    }

    func handleBatchArchive(
        _ entryIDs: Set<UUID>,
        syncedEntries: [VocabularyEntry],
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        let entries = syncedEntries.filter { entryIDs.contains($0.id) }
        var failCount = 0
        let grouped = Dictionary(grouping: entries, by: \.notebookId)

        for (nbId, nbEntries) in grouped {
            let words = nbEntries.map(\.word)
            do {
                let response = try await kgService.batchArchiveCards(words: words, archived: true, notebookId: nbId)
                let updatedSet = Set(response.updated_words)
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
        modelContext.safeSave()
        if failCount > 0 {
            let successCount = entries.count - failCount
            errorMessage = L10n.format("%@/%@ 張卡片已封存，部分失敗", "\(successCount)", "\(entries.count)")
        }
    }

    func handleBatchMove(
        _ entryIDs: Set<UUID>,
        syncedEntries: [VocabularyEntry],
        toNotebook: String,
        fromNotebook: String,
        kgService: any KGServing,
        modelContext: ModelContext
    ) async throws {
        let entries = syncedEntries.filter { entryIDs.contains($0.id) }
        let words = entries.map(\.word)
        try await kgService.moveCards(words: words, fromNotebook: fromNotebook, toNotebook: toNotebook)
        for entry in entries {
            entry.notebookId = toNotebook
        }
        modelContext.safeSave()
    }
}
