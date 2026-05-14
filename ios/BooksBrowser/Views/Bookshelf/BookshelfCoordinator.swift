#if os(iOS)
import Foundation
import SwiftData
import TipKit
import os

@MainActor protocol BookshelfCoordinating: AnyObject, Observable {
    var isImporting: Bool { get set }
    var isLoading: Bool { get }
    var loadingMessage: String { get }
    /// 目前匯入的進度（0.0–1.0）；nil 表示未知或尚未取得（顯示 indeterminate spinner）。
    var loadingProgress: Double? { get }
    var errorMessage: String? { get }
    var errorDiagnosis: String? { get }
    var showError: Bool { get set }
    var showSettings: Bool { get set }
    func presentImporter()
    func presentSettings()
    func dismissError()
    func handleFileImport(_ result: Result<[URL], Error>, modelContext: ModelContext, importService: any BookshelfImporting, toastCoordinator: AppToastCoordinator)
    func deleteBook(_ book: Book, modelContext: ModelContext, fileManager: any BookFileManaging, toastCoordinator: AppToastCoordinator)
}

@Observable @MainActor
final class BookshelfCoordinator: BookshelfCoordinating {
    var isImporting = false
    var isLoading = false
    var loadingMessage = ""
    var loadingProgress: Double?
    var errorMessage: String?
    var errorDiagnosis: String?
    var showError = false
    var showSettings = false

    func presentImporter() {
        isImporting = true
    }

    func presentSettings() {
        showSettings = true
    }

    func dismissError() {
        errorMessage = nil
        errorDiagnosis = nil
        showError = false
    }

    func handleFileImport(
        _ result: Result<[URL], Error>,
        modelContext: ModelContext,
        importService: any BookshelfImporting,
        toastCoordinator: AppToastCoordinator
    ) {
        switch result {
        case .success(let urls):
            guard !urls.isEmpty else { return }
            performBatchImport(
                urls: urls,
                modelContext: modelContext,
                importService: importService,
                toastCoordinator: toastCoordinator
            )
        case .failure(let error):
            let typed = BookshelfImportError.classify(error)
            errorMessage = typed.errorDescription
            errorDiagnosis = typed.diagnosisLabel
            showError = true
        }
    }

    /// Resolve the appropriate import method for a given file extension.
    /// Returns nil if the extension is not supported.
    /// 回傳的 closure 接受 URL + 進度 callback；callback 由背景執行緒呼叫。
    private func importMethod(
        for ext: String,
        using service: any BookshelfImporting
    ) -> ((URL, @Sendable (Double) -> Void) async throws -> ImportedBookDraft)? {
        switch ext {
        case "epub": return { try await service.importBook(from: $0, progress: $1) }
        case "txt":  return { try await service.importTXT(from: $0, progress: $1) }
        case "md":   return { try await service.importMD(from: $0, progress: $1) }
        case "pdf":  return { try await service.importPDF(from: $0, progress: $1) }
        default:     return nil
        }
    }

    func deleteBook(
        _ book: Book,
        modelContext: ModelContext,
        fileManager: any BookFileManaging,
        toastCoordinator: AppToastCoordinator
    ) {
        // Manual cascade: clear bookId on related vocabulary entries
        let bookId = book.id
        var descriptor = FetchDescriptor<VocabularyEntry>()
        descriptor.predicate = #Predicate<VocabularyEntry> { $0.bookId == bookId }
        if let entries = try? modelContext.fetch(descriptor) {
            for entry in entries {
                entry.bookId = nil
            }
        }

        fileManager.deleteBookFile(named: book.epubFileName)
        modelContext.delete(book)
        if modelContext.safeSaveWithToast(toastCoordinator) {
            toastCoordinator.success("已刪除")
        }
    }

    private func performBatchImport(
        urls: [URL],
        modelContext: ModelContext,
        importService: any BookshelfImporting,
        toastCoordinator: AppToastCoordinator
    ) {
        isLoading = true
        loadingProgress = nil
        let total = urls.count
        loadingMessage = total > 1
            ? L10n.string("正在匯入 1 / \(total)...")
            : L10n.string("正在匯入...")

        Task {
            var succeeded = 0
            var failures: [(name: String, diagnosed: BookshelfImportError)] = []

            for (index, url) in urls.enumerated() {
                if total > 1 {
                    loadingMessage = L10n.string("正在匯入 \(index + 1) / \(total)...")
                }
                loadingProgress = 0.0

                let ext = url.pathExtension.lowercased()
                guard let method = importMethod(for: ext, using: importService) else {
                    failures.append((url.lastPathComponent, .unsupportedExtension(ext)))
                    continue
                }

                // 背景 callback hop 回 MainActor 更新 UI
                let onProgress: @Sendable (Double) -> Void = { ratio in
                    Task { @MainActor [weak self] in
                        self?.loadingProgress = ratio
                    }
                }

                do {
                    AppLog.book.info("BookshelfCoordinator: starting import from \(url)")
                    let draft = try await method(url, onProgress)
                    AppLog.book.info("Import succeeded: \(draft.fileName)")
                    AppLog.book.info("Book draft: title=\(draft.title), author=\(draft.author), coverBytes=\(draft.coverImageData?.count ?? 0)")

                    let book = Book(
                        title: draft.title,
                        author: draft.author,
                        coverImageData: draft.coverImageData,
                        fileName: draft.fileName,
                        format: draft.format
                    )
                    modelContext.insert(book)
                    if modelContext.safeSaveWithToast(toastCoordinator) {
                        AppLog.book.info("Book saved: \(book.title)")
                        succeeded += 1
                    } else {
                        failures.append((url.lastPathComponent, .unknown(underlying: "儲存失敗")))
                    }
                } catch {
                    AppLog.book.error("BookshelfCoordinator import error: \(error.localizedDescription)")
                    AppLog.book.error("Error type: \(String(describing: type(of: error)))")
                    let diagnosed = BookshelfImportError.classify(error, sourceURL: url)
                    failures.append((url.lastPathComponent, diagnosed))
                }
            }

            isLoading = false
            loadingMessage = ""
            loadingProgress = nil

            if succeeded > 0 {
                EPUBGuideTip().invalidate(reason: .actionPerformed)
            }

            // 結果回報：依成功/失敗組合決定 toast vs alert
            switch (succeeded, failures.count) {
            case (let s, 0) where s == 1:
                toastCoordinator.success("已匯入")
            case (let s, 0):
                toastCoordinator.success("已匯入 \(s) 本")
            case (0, 1):
                let f = failures[0]
                errorMessage = f.diagnosed.errorDescription ?? f.name
                errorDiagnosis = f.diagnosed.diagnosisLabel
                showError = true
            case (0, let n):
                errorMessage = batchFailureMessage(failures: failures)
                errorDiagnosis = "\(n) 本匯入失敗"
                showError = true
            case (let s, let n):
                toastCoordinator.warning("已匯入 \(s) 本，\(n) 本失敗")
                errorMessage = batchFailureMessage(failures: failures)
                errorDiagnosis = "部分匯入失敗"
                showError = true
            }
        }
    }

    private func batchFailureMessage(failures: [(name: String, diagnosed: BookshelfImportError)]) -> String {
        failures
            .map { "・\($0.name)：\($0.diagnosed.diagnosisLabel)" }
            .joined(separator: "\n")
    }
}
#endif
