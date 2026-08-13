#if DEBUG && targetEnvironment(simulator)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

struct ExploreFixtureContractTests {
    private static var marketingDemoURL: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
            .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
    }

    @Test func fixtureDatasetRequiresTopLevelSharedDecks() throws {
        let complete = try FixtureDatasetStoreTests.completeV2DatasetData(
            """
            {
              "schema": "kg.fixture.dataset.v2",
              "datasetID": "missing-shared-decks"
            }
            """
        )
        var object = try #require(
            try JSONSerialization.jsonObject(with: complete) as? [String: Any]
        )
        object.removeValue(forKey: "sharedDecks")
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])

        #expect(throws: DecodingError.self) {
            try FixtureDatasetStore.decode(data)
        }
    }

    @Test func checkedInFixtureArtifactsContainNoLegacyGenericAssetWire() throws {
        let repositoryURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
        let urls = [
            repositoryURL.appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json"),
            repositoryURL.appendingPathComponent("ops/demo/generated/ios_fixture_dataset.json"),
        ]
        for url in urls {
            let json = try String(contentsOf: url, encoding: .utf8)
            #expect(!json.contains("\"assetInodes\""))
            #expect(!json.contains("inode:"))
        }
    }

    @Test func assetResolutionRejectsStaleAbsoluteSourcePath() throws {
        let relativeSourcePath = "ios/BooksAndVocab/Assets.xcassets/AppIconImage.imageset/app_icon.png"
        let staleAbsoluteSourcePath = "/Users/chenliangyu/project/kg/\(relativeSourcePath)"
        let sourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
            .appendingPathComponent(relativeSourcePath)
        let sourceData = try Data(contentsOf: sourceURL)
        let sha256 = try FixtureDatasetStore.sha256Hex(for: sourceURL)
        let installAs = "ExploreContractTests/\(UUID().uuidString)/cover.png"

        var object = try #require(
            try JSONSerialization.jsonObject(
                with: Data(contentsOf: Self.marketingDemoURL)
            ) as? [String: Any]
        )
        var assets = try #require(object["assets"] as? [String: Any])
        var images = try #require(assets["images"] as? [String: Any])
        var asset = try #require(images["explore_required"] as? [String: Any])
        asset["sourcePath"] = staleAbsoluteSourcePath
        asset["sha256"] = sha256
        asset["byteSize"] = sourceData.count
        asset["installAs"] = installAs
        images["explore_required"] = asset
        assets["images"] = images
        object["assets"] = assets
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])

        let staleAsset = try #require(
            try FixtureDatasetStore.decode(data).assets.asset(for: "images.explore_required")
        )
        #expect(throws: (any Error).self) {
            try FixtureDatasetStore.resolveSourceURL(for: staleAsset)
        }
    }

    @Test func assetResolutionUsesCanonicalManifestAndInstalledSnapshot() throws {
        let data = try Data(contentsOf: Self.marketingDemoURL)
        let asset = try #require(
            try FixtureDatasetStore.decode(data).assets.asset(for: "images.explore_required")
        )
        #expect(!asset.sourcePath.hasPrefix("/"))
        #expect(asset.sourcePath == "ios/BooksAndVocab/Assets.xcassets/AppIconImage.imageset/app_icon.png")
        let installAs = "ExploreContractTests/\(UUID().uuidString)/cover.png"
        var object = try #require(
            try JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        var assets = try #require(object["assets"] as? [String: Any])
        var images = try #require(assets["images"] as? [String: Any])
        var imageAsset = try #require(images["explore_required"] as? [String: Any])
        imageAsset["installAs"] = installAs
        images["explore_required"] = imageAsset
        assets["images"] = images
        object["assets"] = assets
        let installData = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])

        let installed = try FixtureDatasetStore.withTestingData(installData) {
            try FixtureDatasetStore.requireInstalledAsset(ref: "images.explore_required")
        }
        #expect(installed.sha256 == asset.sha256)
        #expect(installed.byteSize == asset.byteSize)
        #expect(installed.contentType == "image/png")
        #expect(installed.fileSystemInode > 0)
        #expect(FileManager.default.fileExists(atPath: installed.url.path))
        #expect(installed.url.path.hasSuffix(installAs))
        try? FileManager.default.removeItem(at: installed.url)
    }

    @Test @MainActor func exploreFixtureServiceFailsThenProjectsRetryThroughProductionService() async throws {
        let data = try Data(contentsOf: Self.marketingDemoURL)
        try await FixtureDatasetStore.withTestingData(data) {
            let container = ExploreFixtureMaterializer.makeContainer(
                for: .retry,
                seedCatalog: false
            )
            let service = ExploreUIWorldCatalogService(fixtureID: .retry)

            let first = await service.syncAll(context: container.mainContext)
            #expect(first == .listFetchFailed)
            #expect(try container.mainContext.fetch(FetchDescriptor<SharedDeck>()).isEmpty)

            let second = await service.syncAll(context: container.mainContext)
            #expect(second == .completed(catalogCount: 1))
            let decks = try container.mainContext.fetch(FetchDescriptor<SharedDeck>())
            let deck = try #require(decks.first)
            #expect(deck.coverAssetID == "images.explore_required")
            #expect(
                deck.coverImagePath.map { FileManager.default.fileExists(atPath: $0) } == .some(true)
            )
            #expect(deck.coverImageSHA256 == "2383e224c5b09040a56b840897e1ea4028c0bb401aafb2335c20e50a7f8ff109")
            #expect(deck.coverImageByteSize == 30129)
            #expect(deck.coverImageContentType == "image/png")
            #expect(deck.coverImageFileSystemInode ?? 0 > 0)
            let reloadedContext = ModelContext(container)
            let persistedDeck = try #require(
                reloadedContext.fetch(FetchDescriptor<SharedDeck>()).first
            )
            #expect(persistedDeck.coverImageFileSystemInode == nil)
        }
    }

    @Test @MainActor func exploreFixtureServiceCanExposePartialCacheFromRealFailure() async throws {
        let data = try Data(contentsOf: Self.marketingDemoURL)
        try await FixtureDatasetStore.withTestingData(data) {
            let container = ExploreFixtureMaterializer.makeContainer(
                for: .retry,
                seedCatalog: false
            )
            let service = ExploreUIWorldCatalogService(
                fixtureID: .retry,
                initialCacheFixtureID: .loaded
            )

            let outcome = await service.syncAll(context: container.mainContext)
            #expect(outcome == .listFetchFailed)
            let deckCount = try container.mainContext.fetch(FetchDescriptor<SharedDeck>()).count
            #expect(
                ExplorePhase.resolve(
                    isSyncing: false,
                    syncFailed: true,
                    totalDeckCount: deckCount,
                    filteredCount: deckCount,
                    isFilteringOrSearching: false
                ) == .partial
            )
        }
    }

    @Test func sharedDeckWorldPartitionsRequiredAndCounterexampleAssets() throws {
        let catalog = try UIWorldSharedDeckCatalogSeed(
                fixtures: [
                    "loading": .init(
                        label: "explore-loading",
                        phase: .loading,
                        retryPhase: nil,
                        deckIDs: ["deck_official_gre_high_freq"],
                        assetIDs: ["images.explore_required"]
                    ),
                    "loaded": .init(
                        label: "explore-loaded",
                        phase: .loaded,
                        retryPhase: nil,
                        deckIDs: ["deck_official_gre_high_freq"],
                        assetIDs: ["images.explore_required"]
                    ),
                    "empty": .init(
                        label: "explore-empty",
                        phase: .empty,
                        retryPhase: nil,
                        deckIDs: [],
                        assetIDs: ["images.explore_required_empty"]
                    ),
                    "retry": .init(
                        label: "explore-retry",
                        phase: .error,
                        retryPhase: .loaded,
                        deckIDs: ["deck_official_gre_high_freq"],
                        assetIDs: ["images.explore_required"]
                    ),
                    "empty-counterexample": .init(
                        label: "explore-empty-counterexample",
                        phase: .empty,
                        retryPhase: nil,
                        deckIDs: [],
                        assetIDs: ["images.explore_counterexample_empty"]
                    ),
                    "retry-counterexample": .init(
                        label: "explore-retry-counterexample",
                        phase: .error,
                        retryPhase: .loaded,
                        deckIDs: ["deck_counterexample_retry"],
                        assetIDs: ["images.explore_counterexample_retry"]
                    ),
                ],
                decks: [
                    "deck_official_gre_high_freq": .init(
                        remoteId: "deck_official_gre_high_freq",
                        title: "Required deck",
                        assetID: "images.explore_required"
                    ),
                    "deck_counterexample_retry": .init(
                        remoteId: "deck_counterexample_retry",
                        title: "Counterexample retry deck",
                        assetID: "images.explore_counterexample_retry"
                    ),
                ]
        )

        #expect(catalog.requiredFixtureLabels == [
            "explore-loading",
            "explore-loaded",
            "explore-empty",
            "explore-retry",
        ])
        #expect(catalog.counterexampleFixtureLabels == [
            "explore-empty-counterexample",
            "explore-retry-counterexample",
        ])
        #expect(catalog.requiredAssetIDs.isDisjoint(with: catalog.counterexampleAssetIDs))
        #expect(catalog.requiredDeckIDs.isDisjoint(with: catalog.counterexampleDeckIDs))
        #expect(catalog.decks["deck_counterexample_retry"]?.assetID == "images.explore_counterexample_retry")
    }

    @Test func sharedDeckWorldProjectsProductionSummaryFromManifestSeed() throws {
        let seed = UIWorldSharedDeckSeed(
            remoteId: "deck_counterexample_retry",
            title: "Counterexample retry deck",
            authorLabel: "Counterexample",
            isOfficial: false,
            category: "counterexample",
            languagePair: "en-zh",
            tags: ["counterexample"],
            cardCount: 1,
            downloadCount: 0,
            ratingAvg: nil,
            ratingCount: 0,
            color: "#B8C9A8",
            coverPattern: "dots",
            updatedAt: "2026-08-13T00:00:00Z",
            assetID: "images.explore_counterexample_retry"
        )

        let summary = seed.productionSummary
        #expect(summary.deckId == "deck_counterexample_retry")
        #expect(summary.title == "Counterexample retry deck")
        #expect(summary.authorLabel == "Counterexample")
        #expect(summary.isOfficial == false)
        #expect(summary.category == "counterexample")
        #expect(summary.tags == ["counterexample"])
        #expect(summary.cardCount == 1)
    }

    @Test func fixtureDatasetV2ReadsSharedDeckManifestBeforeProductionProjection() throws {
        let catalog = try UIWorldSharedDeckCatalogSeed(
            fixtures: [
                "loading": .init(
                    label: "explore-loading",
                    phase: .loading,
                    retryPhase: nil,
                    deckIDs: ["deck_official_gre_high_freq"],
                    assetIDs: ["images.explore_required"]
                ),
                "loaded": .init(
                    label: "explore-loaded",
                    phase: .loaded,
                    retryPhase: nil,
                    deckIDs: ["deck_official_gre_high_freq"],
                    assetIDs: ["images.explore_required"]
                ),
                "empty": .init(
                    label: "explore-empty",
                    phase: .empty,
                    retryPhase: nil,
                    deckIDs: [],
                    assetIDs: ["images.explore_required_empty"]
                ),
                "retry": .init(
                    label: "explore-retry",
                    phase: .error,
                    retryPhase: .loaded,
                deckIDs: ["deck_official_gre_high_freq"],
                    assetIDs: ["images.explore_required"]
                ),
                "empty-counterexample": .init(
                    label: "explore-empty-counterexample",
                    phase: .empty,
                    retryPhase: nil,
                    deckIDs: [],
                    assetIDs: ["images.explore_counterexample_empty"]
                ),
                "retry-counterexample": .init(
                    label: "explore-retry-counterexample",
                    phase: .error,
                    retryPhase: .loaded,
                    deckIDs: ["deck_counterexample_retry"],
                    assetIDs: ["images.explore_counterexample_retry"]
                ),
            ],
            decks: [
            "deck_official_gre_high_freq": .init(
                remoteId: "deck_official_gre_high_freq",
                    title: "Required deck",
                    isOfficial: true,
                    category: "exam",
                    cardCount: 12,
                    assetID: "images.explore_required"
                ),
                "deck_counterexample_retry": .init(
                    remoteId: "deck_counterexample_retry",
                    title: "Counterexample retry deck",
                    category: "counterexample",
                    cardCount: 1,
                    assetID: "images.explore_counterexample_retry"
                ),
            ]
        )

        let encodedCatalog = try JSONSerialization.jsonObject(
            with: JSONEncoder().encode(catalog)
        )
        func imageAsset(_ name: String) -> [String: Any] {
            [
                "sourcePath": "/tmp/\(name).png",
                "sha256": String(repeating: "a", count: 64),
                "installAs": "Explore/\(name).png",
                "byteSize": 1,
                "contentType": "image/png",
            ]
        }
        let object: [String: Any] = [
            "schema": "kg.fixture.dataset.v2",
            "datasetID": "explore-contract",
            "assets": [
                "books": [:],
                "audio": [:],
                "subtitles": [:],
                "text": [:],
                "images": [
                    "explore_required": imageAsset("required"),
                    "explore_required_empty": imageAsset("required-empty"),
                    "explore_counterexample_empty": imageAsset("counterexample-empty"),
                    "explore_counterexample_retry": imageAsset("counterexample-retry"),
                ],
            ],
            "sharedDecks": encodedCatalog,
        ]
        let raw = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        let complete = try FixtureDatasetStoreTests.completeV2DatasetData(
            String(decoding: raw, as: UTF8.self)
        )

        let document = try FixtureDatasetStore.decode(complete)
        let loaded = document.sharedDecks
        #expect(loaded.requiredAssetIDs == Set([
            "images.explore_required",
            "images.explore_required_empty",
        ]))
        #expect(loaded.counterexampleAssetIDs == Set([
            "images.explore_counterexample_empty",
            "images.explore_counterexample_retry",
        ]))
        #expect(
            loaded.decks["deck_official_gre_high_freq"]?.productionSummary.deckId
                == "deck_official_gre_high_freq"
        )
        #expect(loaded.decks["deck_official_gre_high_freq"]?.productionSummary.cardCount == 12)
    }
}
#endif
