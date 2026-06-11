#if DEBUG
import Testing
@testable import BooksAndVocab

@Suite struct NotebookFixturesTests {
    @Test func notebookFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = NotebookFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = NotebookFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "notebook.populated",
            "notebook.single",
        ])

        #expect(catalogKeys == previewKeys)
    }
}
#endif
