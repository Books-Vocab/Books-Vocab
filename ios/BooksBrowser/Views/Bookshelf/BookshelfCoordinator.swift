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
    func handleFileImport(_ result: Result<[URL], Error>, modelContext: ModelContext, importService: any BookshelfImporting)
    func deleteBook(_ book: Book, modelContext: ModelContext, fileManager: any BookFileManaging)
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
        importService: any BookshelfImporting
    ) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            importEPUB(from: url, modelContext: modelContext, importService: importService)
        case .failure(let error):
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    func deleteBook(
        _ book: Book,
        modelContext: ModelContext,
        fileManager: any BookFileManaging
    ) {
        // Manual cascade: clear bookId on related vocabulary entries
        if let entries = try? modelContext.fetch(FetchDescriptor<VocabularyEntry>()) {
            let bookId = book.id
            for entry in entries where entry.bookId == bookId {
                entry.bookId = nil
            }
        }

        fileManager.deleteBookFile(named: book.epubFileName)
        modelContext.delete(book)
    }

    private func importEPUB(
        from url: URL,
        modelContext: ModelContext,
        importService: any BookshelfImporting
    ) {
        isLoading = true
        loadingMessage = L10n.string("正在匯入書籍...")

        Task {
            do {
                AppLog.book.info("BookshelfCoordinator: starting import from \(url)")
                loadingMessage = L10n.string("正在解析 EPUB...")

                let draft = try await importService.importBook(from: url)
                AppLog.book.info("Import succeeded: \(draft.epubFileName)")
                AppLog.book.info("Book draft: title=\(draft.title), author=\(draft.author), coverBytes=\(draft.coverImageData?.count ?? 0)")

                loadingMessage = L10n.string("正在儲存...")

                let book = Book(
                    title: draft.title,
                    author: draft.author,
                    coverImageData: draft.coverImageData,
                    epubFileName: draft.epubFileName
                )

                modelContext.insert(book)
                modelContext.safeSave()
                EPUBGuideTip().invalidate(reason: .actionPerformed)
                AppLog.book.info("Book saved: \(book.title)")

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
