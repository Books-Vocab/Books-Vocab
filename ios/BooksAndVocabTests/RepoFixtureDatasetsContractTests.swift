#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

/// Contract gate for every named UI World under `ops/fixtures/ui_worlds/`.
///
/// `FixtureDatasetStore` is the UI World SoT. A broken dataset must be caught at
/// the contract boundary: each repo dataset must decode, carry a `datasetID`
/// matching its filename, and only key into fixture IDs that exist in the Swift
/// registries.
struct RepoFixtureDatasetsContractTests {
    private static var datasetsDirectory: URL {
        // …/ios/BooksAndVocabTests/RepoFixtureDatasetsContractTests.swift → repo root
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repo root
            .appendingPathComponent("ops/fixtures/ui_worlds", isDirectory: true)
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
            let data = try Data(contentsOf: url)
            let document = try FixtureDatasetStore.decode(data)
            let stem = url.deletingPathExtension().lastPathComponent

            #expect(document.schema == "kg.fixture.dataset.v1", "\(stem): unexpected schema")
            #expect(document.datasetID == stem, "\(stem): datasetID must match filename")

            // Keyed decoding ignores unknown top-level keys, so a domain-level
            // typo ("podcasts") silently drops the whole domain — exactly the
            // failure class this suite exists to close.
            let topLevel = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
            let unknownTopLevel = Set(topLevel.keys).subtracting(FixtureDatasetDocument.knownTopLevelKeys)
            #expect(
                unknownTopLevel.isEmpty,
                "\(stem): unknown top-level keys \(unknownTopLevel.sorted()) would be silently ignored"
            )

            expectKnownKeys(document.settings.keys, SettingsFixtureID.self, domain: "settings", dataset: stem)
            expectKnownKeys(document.auth.keys, UIWorldAuthFixtureID.self, domain: "auth", dataset: stem)
            expectKnownKeys(document.entitlements.keys, UIWorldEntitlementsFixtureID.self, domain: "entitlements", dataset: stem)
            expectKnownKeys(document.bookshelf.keys, BookshelfFixtureID.self, domain: "bookshelf", dataset: stem)
            expectKnownKeys(document.todayReview.keys, TodayReviewFixtureID.self, domain: "todayReview", dataset: stem)
            expectKnownKeys(document.notebook.keys, NotebookFixtureID.self, domain: "notebook", dataset: stem)
            expectKnownKeys(document.podcast.keys, PodcastFixtureID.self, domain: "podcast", dataset: stem)

            // Duplicate identities render undefined (ForEach ids / notebookId
            // joins derive from them), so they must be unique within a seed.
            for (fixtureKey, seed) in document.podcast {
                let numbers = seed.episodes.map(\.episodeNumber)
                #expect(
                    Set(numbers).count == numbers.count,
                    "\(stem): podcast.\(fixtureKey) has duplicate episodeNumber values"
                )
            }
            for (fixtureKey, seed) in document.notebook {
                let ids = seed.notebooks.map(\.remoteId)
                #expect(
                    Set(ids).count == ids.count,
                    "\(stem): notebook.\(fixtureKey) has duplicate notebook remoteId values"
                )
            }
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
