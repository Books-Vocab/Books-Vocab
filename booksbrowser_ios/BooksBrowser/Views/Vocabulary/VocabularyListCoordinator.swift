import Foundation
import SwiftData

@MainActor
final class VocabularyListCoordinator: ObservableObject {
    @Published var showExportSheet = false
    @Published var showSyncView = false
    @Published var showSettings = false
    @Published var exportURL: URL?
    @Published var isForceRefreshing = false
    @Published var selectedEntry: VocabularyEntry?
    @Published var activeReviewSession: TodayReviewSession?

    func presentSyncView() {
        showSyncView = true
    }

    func presentSettings() {
        showSettings = true
    }

    func exportCSV(entries: [VocabularyEntry]) {
        exportURL = VocabularyExporter.exportAsCSV(entries: entries)
    }

    func exportJSON(entries: [VocabularyEntry]) {
        exportURL = VocabularyExporter.exportAsJSON(entries: entries)
    }

    func exportAnki(entries: [VocabularyEntry]) {
        exportURL = VocabularyExporter.exportAsAnki(entries: entries)
    }

    func startKnowledgeReview(entries: [VocabularyEntry]) {
        guard !entries.isEmpty else { return }
        activeReviewSession = TodayReviewSession(entries: entries)
    }

    func handlePendingRowTap(_ entryID: UUID, pendingEntries: [VocabularyEntry]) {
        selectedEntry = pendingEntries.first { $0.id == entryID }
    }

    func handlePendingActionTap(
        _ entryID: UUID,
        pendingEntries: [VocabularyEntry],
        modelContext: ModelContext
    ) {
        guard let entry = pendingEntries.first(where: { $0.id == entryID }) else { return }
        handlePendingRemoval(entry, modelContext: modelContext)
    }

    func forceRefresh(
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        guard !isForceRefreshing else { return }
        isForceRefreshing = true
        defer { isForceRefreshing = false }

        await kgService.clearLocalData(container: modelContext.container, reason: "force_refresh")
        try? await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
        await kgService.healthCheck()
    }

    private func handlePendingRemoval(_ entry: VocabularyEntry, modelContext: ModelContext) {
        if entry.actionType == "delete" {
            entry.syncStatus = 1
            entry.actionType = "add"
        } else {
            modelContext.delete(entry)
        }
        try? modelContext.save()
    }
}
