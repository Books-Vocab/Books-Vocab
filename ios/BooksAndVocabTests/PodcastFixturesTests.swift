#if DEBUG
import Testing
@testable import BooksAndVocab

@Suite struct PodcastFixturesTests {
    @Test func podcastFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = PodcastFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = PodcastFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "podcast.shelf_continue",
            "podcast.shelf_single",
        ])

        #expect(catalogKeys == previewKeys)
    }
}
#endif
