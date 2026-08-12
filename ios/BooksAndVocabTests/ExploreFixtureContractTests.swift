#if DEBUG && targetEnvironment(simulator)
import Foundation
import Testing
@testable import BooksAndVocab

struct ExploreFixtureContractTests {
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
        let loaded = try #require(document.sharedDecks)
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
