import Foundation
import SwiftData
import os

@MainActor protocol VocabularyListCoordinating: AnyObject, Observable {
    var showSyncView: Bool { get set }
    var showSettings: Bool { get set }
    var exportURL: URL? { get }
    var activeReviewSession: TodayReviewSession? { get set }
    func presentSyncView()
    func presentSettings()
    func exportCSV(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator)
    func exportJSON(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator)
    func exportAnki(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator)
    func startKnowledgeReview(entries: [VocabularyEntry])
}

@Observable @MainActor
final class VocabularyListCoordinator: VocabularyListCoordinating {
    var showSyncView = false
    var showSettings = false
    var exportURL: URL?
    var activeReviewSession: TodayReviewSession?

    func presentSyncView() {
        showSyncView = true
    }

    func presentSettings() {
        showSettings = true
    }

    func exportCSV(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator) {
        runExport(VocabularyExporter.exportAsCSV, entries: entries, toastCoordinator: toastCoordinator)
    }

    func exportJSON(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator) {
        runExport(VocabularyExporter.exportAsJSON, entries: entries, toastCoordinator: toastCoordinator)
    }

    func exportAnki(entries: [VocabularyEntry], toastCoordinator: AppToastCoordinator) {
        runExport(VocabularyExporter.exportAsAnki, entries: entries, toastCoordinator: toastCoordinator)
    }

    /// 共用匯出流程：產生暫存檔 URL，失敗時統一彈出錯誤 toast。
    private func runExport(
        _ makeFile: ([VocabularyEntry]) -> URL?,
        entries: [VocabularyEntry],
        toastCoordinator: AppToastCoordinator
    ) {
        exportURL = makeFile(entries)
        if exportURL == nil { toastCoordinator.error("匯出失敗".localized) }
    }

    func startKnowledgeReview(entries: [VocabularyEntry]) {
        guard !entries.isEmpty else { return }
        activeReviewSession = TodayReviewSession(entries: entries)
    }
}
