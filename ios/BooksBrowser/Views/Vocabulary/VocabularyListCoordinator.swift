import Foundation
import SwiftData
import os

@MainActor protocol VocabularyListCoordinating: AnyObject, Observable {
    var showExportSheet: Bool { get set }
    var showSyncView: Bool { get set }
    var showSettings: Bool { get set }
    var exportURL: URL? { get }
    var selectedEntry: VocabularyEntry? { get set }
    var activeReviewSession: TodayReviewSession? { get set }
    func presentSyncView()
    func presentSettings()
    func exportCSV(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator)
    func exportJSON(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator)
    func exportAnki(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator)
    func startKnowledgeReview(entries: [VocabularyEntry])
    func handlePendingRowTap(_ entryID: UUID, pendingEntries: [VocabularyEntry])
    func handlePendingActionTap(_ entryID: UUID, pendingEntries: [VocabularyEntry], modelContext: ModelContext, toastCoordinator: AppToastCoordinator)
}

@Observable @MainActor
final class VocabularyListCoordinator: VocabularyListCoordinating {
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

    func exportCSV(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator) {
        exportURL = VocabularyExporter.exportAsCSV(entries: entries)
        if exportURL == nil { toastCoordinator.error("匯出失敗") }
    }

    func exportJSON(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator) {
        exportURL = VocabularyExporter.exportAsJSON(entries: entries)
        if exportURL == nil { toastCoordinator.error("匯出失敗") }
    }

    func exportAnki(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator) {
        exportURL = VocabularyExporter.exportAsAnki(entries: entries)
        if exportURL == nil { toastCoordinator.error("匯出失敗") }
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
        modelContext: ModelContext,
        toastCoordinator: AppToastCoordinator
    ) {
        guard let entry = pendingEntries.first(where: { $0.id == entryID }) else { return }
        handlePendingRemoval(entry, modelContext: modelContext, toastCoordinator: toastCoordinator)
    }

    private func handlePendingRemoval(_ entry: VocabularyEntry, modelContext: ModelContext, toastCoordinator: AppToastCoordinator) {
        if entry.syncAction == .delete {
            entry.markSynced()
        } else {
            modelContext.delete(entry)
        }
        modelContext.safeSaveWithToast(toastCoordinator)
    }
}
