#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

/// Contract gate for every named dataset under `ops/fixtures/catalog/`.
///
/// `FixtureDatasetStore` falls back to embedded recipes when a dataset fails to
/// decode or references unknown fixture IDs, so a broken dataset never crashes —
/// it silently renders the wrong content. This suite turns that silence into a
/// red test: each repo dataset must decode, carry a `datasetID` matching its
/// filename, and only key into fixture IDs that exist in the Swift registries.
struct RepoFixtureDatasetsContractTests {
    private static var datasetsDirectory: URL {
        // …/ios/BooksAndVocabTests/RepoFixtureDatasetsContractTests.swift → repo root
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repo root
            .appendingPathComponent("ops/fixtures/catalog", isDirectory: true)
    }

    private static func datasetURLs() throws -> [URL] {
        try FileManager.default
            .contentsOfDirectory(at: datasetsDirectory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    @Test func repoContainsAtLeastOneDataset() throws {
        #expect(try !Self.datasetURLs().isEmpty)
    }

    @Test func everyRepoDatasetDecodesAndMatchesKnownFixtureIDs() throws {
        for url in try Self.datasetURLs() {
            let document = try FixtureDatasetStore.decode(Data(contentsOf: url))
            let stem = url.deletingPathExtension().lastPathComponent

            #expect(document.schema == "kg.fixture.dataset.v1", "\(stem): unexpected schema")
            #expect(document.datasetID == stem, "\(stem): datasetID must match filename")

            expectKnownKeys(document.settings.keys, SettingsFixtureID.self, domain: "settings", dataset: stem)
            expectKnownKeys(document.bookshelf.keys, BookshelfFixtureID.self, domain: "bookshelf", dataset: stem)
            expectKnownKeys(document.todayReview.keys, TodayReviewFixtureID.self, domain: "todayReview", dataset: stem)
            expectKnownKeys(document.notebook.keys, NotebookFixtureID.self, domain: "notebook", dataset: stem)
            expectKnownKeys(document.podcast.keys, PodcastFixtureID.self, domain: "podcast", dataset: stem)
        }
    }

    private func expectKnownKeys<ID: RawRepresentable & CaseIterable>(
        _ keys: some Sequence<String>,
        _ idType: ID.Type,
        domain: String,
        dataset: String
    ) where ID.RawValue == String {
        let known = Set(idType.allCases.map(\.rawValue))
        let unknown = Set(keys).subtracting(known)
        #expect(
            unknown.isEmpty,
            "\(dataset): domain \(domain) keys \(unknown.sorted()) have no matching fixture ID — they would silently never render"
        )
    }
}
#endif
