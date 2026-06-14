#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

@Suite(.serialized) struct TodayReviewFixturesTests {
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

    @Test func todayReviewFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = TodayReviewFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = TodayReviewFixtures.recipes(for: .catalog).map(\.key.rawValue)
        let snapshotKeys = TodayReviewFixtures.recipes(for: .snapshot).map(\.key.rawValue)

        #expect(previewKeys == [
            "today_review.front",
            "today_review.back",
            "today_review.completed",
            "today_review.autoplay",
            "today_review.autoplayPaused",
            "today_review.productionFront",
            "today_review.productionBack",
            "today_review.longContent",
        ])

        #expect(catalogKeys == previewKeys)
        #expect(snapshotKeys == [
            "today_review.front",
            "today_review.back",
            "today_review.completed",
            "today_review.autoplay",
            "today_review.autoplayPaused",
            "today_review.productionFront",
            "today_review.productionBack",
        ])
    }

    @Test func todayReviewFixtureRegistryIsManifestOnly() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Support/Fixtures/TodayReview/TodayReviewFixtures.swift")
        let source = try String(contentsOf: url, encoding: .utf8)
        let registryStart = try #require(source.range(of: "private static let registry"))
        let registryEnd = try #require(source.range(of: "static func recipes", range: registryStart.upperBound..<source.endIndex))
        let registrySource = String(source[registryStart.lowerBound..<registryEnd.lowerBound])
        let adapterStart = try #require(source.range(of: "private enum TodayReviewFixtureAdapter"))
        let fixtureSource = String(source[..<adapterStart.lowerBound])

        #expect(registrySource.contains("TodayReviewFixtureID.allCases.map"))
        #expect(registrySource.contains("FixtureDatasetStore.requireTodayReviewSeed(for: fixtureID)"))
        #expect(!registrySource.contains(".init("), "TodayReview fixture registry must not construct local seed data")
        #expect(!fixtureSource.contains("TodayReviewCardSeed("), "TodayReview fixtures must not keep local card seed constants")
    }

    @Test func repoAndGeneratedDatasetsDeclareEveryTodayReviewFixture() throws {
        let expected = Set(TodayReviewFixtureID.allCases.map(\.rawValue))
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        #expect(Set(repoDocument.todayReview.keys) == expected)
        #expect(Set(generatedDocument.todayReview.keys) == expected)
    }

    @MainActor
    @Test func frontFixtureComesFromUIWorld() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let expectedSeed = try #require(document.todayReview[TodayReviewFixtureID.front.rawValue])
        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let model = TodayReviewFixtures.renderModel(for: .front)
            #expect(model.state.progressText == expectedSeed.progressText)
            #expect(model.state.currentCard?.card.word == expectedSeed.currentCard?.word)
            #expect(model.showFirstRunHint == expectedSeed.showFirstRunHint)
        }
    }
}
#endif
