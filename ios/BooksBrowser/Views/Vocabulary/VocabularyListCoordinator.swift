import Foundation
import SwiftData
import os

@Observable @MainActor
final class VocabularyListCoordinator {
    var showExportSheet = false
    var showSyncView = false
    var showSettings = false
    var exportURL: URL?
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

    private func handlePendingRemoval(_ entry: VocabularyEntry, modelContext: ModelContext) {
        if entry.syncAction == .delete {
            entry.markSynced()
        } else {
            modelContext.delete(entry)
        }
        modelContext.safeSave()
    }
}
