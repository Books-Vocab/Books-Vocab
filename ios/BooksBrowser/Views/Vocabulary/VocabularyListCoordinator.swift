import Foundation
import SwiftData
import os

@Observable @MainActor
final class VocabularyListCoordinator {
    var showExportSheet = false
    var showSyncView = false
    var showSettings = false
    var exportURL: URL?
    var isForceRefreshing = false
    var selectedEntry: VocabularyEntry?
    var activeReviewSession: TodayReviewSession?

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
        do {
            try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
        } catch {
            AppLog.sync.error("Force refresh pullCardsToLocal failed: \(error.localizedDescription)")
        }
        await kgService.healthCheck()
    }

    private func handlePendingRemoval(_ entry: VocabularyEntry, modelContext: ModelContext) {
        if entry.syncAction == .delete {
            entry.markSynced()
        } else {
            modelContext.delete(entry)
        }
        modelContext.safeSave()
    }
}
