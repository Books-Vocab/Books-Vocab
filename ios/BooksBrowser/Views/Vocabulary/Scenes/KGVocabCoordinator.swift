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
        try? modelContext.save()
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

        try? modelContext.save()
        await kgService.healthCheck()
    }
}
