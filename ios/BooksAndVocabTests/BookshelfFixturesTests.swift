#if DEBUG
import Testing
@testable import BooksAndVocab

@Suite struct BookshelfFixturesTests {
    @Test func bookshelfFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = BookshelfFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = BookshelfFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "bookshelf.progress_card",
            "bookshelf.placeholder_card",
            "bookshelf.empty_library",
            "bookshelf.with_books_library",
            "bookshelf.loading_overlay",
        ])

        #expect(catalogKeys == previewKeys)
    }
}
#endif
