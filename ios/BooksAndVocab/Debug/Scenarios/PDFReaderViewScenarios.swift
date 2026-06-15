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
        let books = BookshelfFixtures.books(for: .withBooksLibrary)
        guard let book = books.first(where: { $0.format == .pdf }) else {
            preconditionFailure("UI World bookshelf.with_books_library must declare a PDF book for PDFReaderViewScenarios")
        }
        do {
            let container = try ModelContainer(
                for: Book.self, VocabularyEntry.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            container.mainContext.insert(book)
            try container.mainContext.save()
            self.container = container
            self.book = book
        } catch {
            preconditionFailure("Failed to seed UI World PDF book row: \(error)")
        }
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
