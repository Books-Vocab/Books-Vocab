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
        for entry in pendingDeletes {
            do {
                try await kgService.deleteCard(word: entry.word, notebookId: entry.notebookId)
                modelContext.delete(entry)
            } catch {
                failedCount += 1
                AppLog.kg.error("deleteCard retry failed '\(entry.word)': \(error.localizedDescription)")
            }
        }

        modelContext.safeSave()

        if failedCount > 0 {
            errorMessage = L10n.format("刪除失敗 %@ 筆，稍後將自動重試", "\(failedCount)")
        }

        await kgService.healthCheck()
    }
}
