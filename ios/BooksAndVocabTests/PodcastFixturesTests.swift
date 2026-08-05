#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

@Suite(.serialized) struct PodcastFixturesTests {
    private static var marketingDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
            return try Data(contentsOf: url)
        }
    }

    private static var generatedDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/demo/generated/ios_fixture_dataset.json")
            return try Data(contentsOf: url)
        }
    }

    @Test func podcastFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = PodcastFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = PodcastFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "podcast.shelf_continue",
            "podcast.shelf_single",
        ])

        #expect(catalogKeys == previewKeys)
    }

    @Test func podcastFixtureRegistryIsManifestOnly() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Support/Fixtures/Podcast/PodcastFixtures.swift")
        let source = try String(contentsOf: url, encoding: .utf8)
        let registryStart = try #require(source.range(of: "private static let registry"))
        let registryEnd = try #require(source.range(of: "static func recipes", range: registryStart.upperBound..<source.endIndex))
        let registrySource = String(source[registryStart.lowerBound..<registryEnd.lowerBound])

        #expect(registrySource.contains("PodcastFixtureID.allCases.map"))
        #expect(registrySource.contains("FixtureDatasetStore.requirePodcastSeed(for: fixtureID)"))
        #expect(!registrySource.contains(".init("), "Podcast fixture registry must not construct local seed data")
    }

    @Test func repoAndGeneratedDatasetsDeclareNoUnknownPodcastFixtureKey() throws {
        let expected = Set(PodcastFixtureID.allCases.map(\.rawValue))
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        // FROZEN 2026-08-05 — 凍結前這兩行是雙向 `==`（world keys 必須等於 allCases），
        // 那是「加一個 FixtureID 就得回填兩份 world」的稅源。現只驗單向：world 不得含
        // app 不認識的 key（那種 key 永遠不會 render）。兩行各配一個 non-empty 正控——
        // 沒有正控的 subset 對空集合恆真（假綠）。復業第一步＝改回 `==`，完整配方見正本。
        // 正本 docs/reference/catalog_scope.md §FROZEN。
        #expect(!repoDocument.podcast.isEmpty)
        #expect(Set(repoDocument.podcast.keys).isSubset(of: expected))
        #expect(!generatedDocument.podcast.isEmpty)
        #expect(Set(generatedDocument.podcast.keys).isSubset(of: expected))
    }

    @MainActor
    @Test func shelfContinueFixtureComesFromUIWorld() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let expectedSeed = try #require(document.podcast[PodcastFixtureID.shelfContinue.rawValue])
        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let model = PodcastFixtures.renderModel(for: .shelfContinue)
            #expect(model.series.remoteId == expectedSeed.series.remoteId)
            #expect(model.series.title == expectedSeed.series.title)
            #expect(model.items.map(\.episode.title) == expectedSeed.episodes.map(\.title))
            #expect(model.items.map { $0.progress?.lastPlayedTime } == expectedSeed.episodes.map(\.lastPlayedTime))
        }
    }
}
#endif
