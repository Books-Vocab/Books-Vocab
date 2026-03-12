import Foundation
import SwiftData
import SwiftUI

@Observable @MainActor
final class KGVocabCoordinator {
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
            try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
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
            try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
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
        for entry in pendingDeletes {
            do {
                try await kgService.deleteCard(word: entry.word)
                modelContext.delete(entry)
            } catch {
            }
        }

        modelContext.safeSave()
        await kgService.healthCheck()
    }
}
