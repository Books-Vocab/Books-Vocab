#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `PDFReaderView` surface.
///
/// The backing `Book` and PDF file both come from UI World: the scenario reads
/// `bookshelf.with_books_library`, requires a PDF row with `bookAssetRef`, then
/// materializes that asset through `FixtureDatasetStore.requireInstalledAssetURL`.
/// Missing row, missing asset, bad hash, unsafe install path, or mismatched
/// filename all fail at catalog construction time.
enum PDFReaderViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "PDF Reader View") {
            Scenario("Manifest PDF", layout: .fill) {
                PDFReaderViewScene()
            }
        }
    }
}

// MARK: - Scene harness

private struct PDFReaderViewScene: View {
    let container: ModelContainer
    let book: Book

    init() {
        let container = try! ModelContainer(
            for: Book.self, VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let seed = FixtureDatasetStore.requireBookshelfSeed(for: .withBooksLibrary)
        guard let source = seed.books.first(where: { $0.format == .pdf }) else {
            preconditionFailure("UI World bookshelf.with_books_library must declare a PDF book for PDFReaderViewScenarios")
        }
        guard let ref = source.bookAssetRef?.trimmingCharacters(in: .whitespacesAndNewlines),
              !ref.isEmpty else {
            preconditionFailure("UI World PDF book \(source.title) is missing bookAssetRef")
        }
        do {
            let installedURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: ref)
            guard installedURL.deletingLastPathComponent().standardizedFileURL == Book.localBooksDirectory.standardizedFileURL else {
                preconditionFailure("UI World PDF asset \(ref) must install directly under Books/: \(installedURL.path)")
            }
            guard installedURL.lastPathComponent == source.fileName else {
                preconditionFailure("UI World PDF book fileName \(source.fileName) must match installed asset \(installedURL.lastPathComponent)")
            }
        } catch {
            preconditionFailure("Failed to install UI World PDF asset \(ref): \(error)")
        }

        let book = Book(
            title: source.title,
            author: source.author,
            fileName: source.fileName,
            format: source.format
        )
        book.progression = source.progression
        book.dateAdded = source.dateAdded
        book.dateLastRead = source.dateLastRead
        container.mainContext.insert(book)
        do {
            try container.mainContext.save()
        } catch {
            preconditionFailure("Failed to seed UI World PDF book row: \(error)")
        }
        self.container = container
        self.book = book
    }

    var body: some View {
        AppThemeContainer {
            PDFReaderView(book: book)
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
