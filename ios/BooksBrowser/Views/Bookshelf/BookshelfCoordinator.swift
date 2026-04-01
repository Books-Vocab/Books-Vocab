import Foundation
import SwiftData
import TipKit
import os

@MainActor protocol BookshelfCoordinating: AnyObject, Observable {
    var isImporting: Bool { get set }
    var isLoading: Bool { get }
    var loadingMessage: String { get }
    var errorMessage: String? { get }
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
    var errorMessage: String?
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
            guard let url = urls.first else { return }
            let ext = url.pathExtension.lowercased()
            let importMethod: (URL) async throws -> ImportedBookDraft
            switch ext {
            case "epub": importMethod = importService.importBook
            case "txt":  importMethod = importService.importTXT
            case "md":   importMethod = importService.importMD
            case "pdf":  importMethod = importService.importPDF
            default:
                errorMessage = "不支援的格式：.\(ext)"
                showError = true
                return
            }
            performImport(url: url, modelContext: modelContext, method: importMethod, toastCoordinator: toastCoordinator)
        case .failure(let error):
            errorMessage = error.localizedDescription
            showError = true
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
        modelContext.safeSaveWithToast(toastCoordinator)
        toastCoordinator.success("已刪除")
    }

    private func performImport(
        url: URL,
        modelContext: ModelContext,
        method: @escaping (URL) async throws -> ImportedBookDraft,
        toastCoordinator: AppToastCoordinator
    ) {
        isLoading = true
        loadingMessage = L10n.string("正在匯入...")

        Task {
            do {
                AppLog.book.info("BookshelfCoordinator: starting import from \(url)")

                let draft = try await method(url)
                AppLog.book.info("Import succeeded: \(draft.fileName)")
                AppLog.book.info("Book draft: title=\(draft.title), author=\(draft.author), coverBytes=\(draft.coverImageData?.count ?? 0)")

                loadingMessage = L10n.string("正在儲存...")

                let book = Book(
                    title: draft.title,
                    author: draft.author,
                    coverImageData: draft.coverImageData,
                    fileName: draft.fileName,
                    format: draft.format
                )

                modelContext.insert(book)
                modelContext.safeSave()
                EPUBGuideTip().invalidate(reason: .actionPerformed)
                AppLog.book.info("Book saved: \(book.title)")
                toastCoordinator.success("已匯入")

                isLoading = false
                loadingMessage = ""
            } catch {
                AppLog.book.error("BookshelfCoordinator import error: \(error.localizedDescription)")
                AppLog.book.error("Error type: \(String(describing: type(of: error)))")
                isLoading = false
                loadingMessage = ""
                errorMessage = "\(error)"
                showError = true
            }
        }
    }
}
