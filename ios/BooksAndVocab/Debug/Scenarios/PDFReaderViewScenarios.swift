#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `PDFReaderView` surface.
///
/// `PDFReaderView(book:)` loads its document in `.task { loadDocument() }`, which
/// short-circuits to a deterministic `loadError` state when the backing file is
/// unreadable — exactly the case for a synthetic `Book` whose `fileName` points
/// at no on-disk file. That makes the "file unavailable" surface fully
/// catalogable without touching the filesystem or network. The view also
/// `@Query`s `VocabularyEntry` (`actionType != "delete"`); a fresh in-memory
/// store satisfies it. Seeding runs in a (nonisolated) scene `init`; safe under
/// Playbook's main-thread rendering (mirrors `StatsViewScene`).
///
/// Note: rendering a *successfully loaded* PDF would require bundling a real
/// fixture file into the catalog target — out of scope here; the error/empty
/// surface is the catalogable, deterministic state.
enum PDFReaderViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "PDF Reader View") {
            Scenario("File unavailable (iCloud / missing)", layout: .fill) {
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
        let book = Book(
            title: "Sample PDF",
            author: "Author",
            fileName: "catalog-missing.pdf",
            format: .pdf
        )
        container.mainContext.insert(book)
        try? container.mainContext.save()
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
