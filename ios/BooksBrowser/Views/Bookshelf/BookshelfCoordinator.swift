import Foundation
import SwiftData

@MainActor
final class BookshelfCoordinator: ObservableObject {
    @Published var isImporting = false
    @Published var isLoading = false
    @Published var loadingMessage = ""
    @Published var errorMessage: String?
    @Published var showError = false
    @Published var showSettings = false

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

        Task { @MainActor in
            do {
                print("🚀 BookshelfCoordinator: starting import from \(url)")
                loadingMessage = L10n.string("正在解析 EPUB...")

                let draft = try await importService.importBook(from: url)
                print("🚀 import succeeded: \(draft.epubFileName)")
                print("🚀 book draft: title=\(draft.title), author=\(draft.author), coverBytes=\(draft.coverImageData?.count ?? 0)")

                loadingMessage = L10n.string("正在儲存...")

                let book = Book(
                    title: draft.title,
                    author: draft.author,
                    coverImageData: draft.coverImageData,
                    epubFileName: draft.epubFileName
                )

                modelContext.insert(book)
                try? modelContext.save()
                print("🚀 book saved: \(book.title)")

                isLoading = false
                loadingMessage = ""
            } catch {
                print("❌ BookshelfCoordinator import error: \(error)")
                print("❌ error type: \(type(of: error))")
                isLoading = false
                loadingMessage = ""
                errorMessage = "\(error)"
                showError = true
            }
        }
    }
}
