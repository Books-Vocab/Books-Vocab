#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite(.serialized)
struct UIWorldVocabularyInheritanceTests {
    private static var marketingDemoData: Data {
        get throws {
            try Data(contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json"))
        }
    }

    @Test @MainActor func p11AndReviewStateFixtureIDsRemainStable() {
        #expect(UIWorldVocabularyFixtureID.p11ReviewMix.rawValue == "p11.644.reviewMix")
        #expect(UIWorldVocabularyFixtureID.reviewStateMixed.rawValue == "review.mixed")
        #expect(UITestFixtureSeed.vocabularyFixtureID(for: "p11.644.reviewMix") == .p11ReviewMix)
        #expect(UITestFixtureSeed.vocabularyFixtureID(for: "review.mixed") == .reviewStateMixed)
        #expect(UITestFixtureSeed.vocabularyFixtureID(for: "P11") == nil)
    }

    @Test @MainActor func inheritanceMaterializesRecursivelyAndRejectsCycles() throws {
        let data = try FixtureDatasetStoreTests.completeV2DatasetData(Self.inheritanceDataset)
        let document = try FixtureDatasetStore.decode(data)
        let seed = try #require(document.vocabulary["review.mixed"])

        #expect(seed.baseFixture == nil, "resolved seeds must not leak inheritance into materializers")
        #expect(seed.entries.map(\.word) == ["alpha"])
        #expect(seed.entryOverrides.count == 1)
        let overlay = try #require(seed.entryOverrides.first)
        #expect(overlay.reviewCount == 3)
        #expect(overlay.nextReviewAt == Date(timeIntervalSince1970: 1_800_000_000 - 60))

        let container = try ModelContainer(
            for: VocabularyEntry.self, Notebook.self, ReviewRecord.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let entries = try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)
        let entry = try #require(entries.first)
        #expect(entry.reviewState(at: Date(timeIntervalSince1970: 1_800_000_000)) == .due)

        let cyclicData = try FixtureDatasetStoreTests.completeV2DatasetData(Self.cyclicDataset)
        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(cyclicData)
        }
    }

    @Test func inheritanceRejectsDuplicateOverrideAcrossChain() throws {
        let data = try FixtureDatasetStoreTests.completeV2DatasetData(
            Self.duplicateOverrideAcrossInheritanceDataset
        )
        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(data)
        }
    }

    @Test func inheritedReviewHistoryMayReferenceResolvedBaseEntry() throws {
        let data = try FixtureDatasetStoreTests.completeV2DatasetData(
            Self.inheritedReviewHistoryDataset
        )
        let document = try FixtureDatasetStore.decode(data)
        let seed = try #require(document.vocabulary["p11.644.reviewMix"])

        #expect(seed.baseFixture == nil)
        #expect(seed.entries.map(\.word) == ["alpha"])
        #expect(seed.reviewHistory.map(\.word) == ["alpha"])
    }

    @Test func directSeedStillRejectsReviewHistoryOutsideItsEntries() throws {
        let dataset = FixtureDatasetStoreTests.vocabularyDataset(
            datasetID: "direct-review-history-missing-entry",
            entriesJSON: FixtureDatasetStoreTests.fullVocabularyEntryJSON(word: "anchored"),
            reviewHistoryJSON: """
            [{
              "word": "orphaned", "feedback": 1,
              "reviewedAt": "2026-08-12T00:00:00Z"
            }]
            """
        )
        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(
                FixtureDatasetStoreTests.completeV2DatasetData(dataset)
            )
        }
    }

    @Test @MainActor func p11MaterializesTheCanonicalReviewContract() throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let p11 = FixtureDatasetStore.requireVocabularySeed(for: .p11ReviewMix)

            #expect(p11.baseFixture == nil)
            #expect(p11.entries.count == 644)
            #expect(p11.entryOverrides.count == 644)

            let p11Container = try ModelContainer(
                for: VocabularyEntry.self, Notebook.self, ReviewRecord.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let p11Entries = try UITestFixtureSeed.insertVocabularySeed(
                p11,
                into: p11Container.mainContext
            )
            let now = Date(timeIntervalSince1970: 1_800_000_000)
            let classified = VocabularyEntryPresentation.classifyKnowledgeEntries(
                in: p11Entries,
                now: now
            )
            #expect(p11Entries.count == 644)
            #expect(p11Entries.allSatisfy { $0.shouldAppearInReview })
            #expect(classified.unlearnedCount == 14)
            #expect(classified.dueCount == 503)
            #expect(classified.reviewedCount == 127)
            #expect(classified.unlearnedCount + classified.dueCount == 517)

        }
    }

    private static let inheritanceDataset = """
    {
      "schema": "kg.fixture.dataset.v2",
      "datasetID": "inheritance-test",
      "vocabulary": {
        "vocabListLong": {
          "notebookRemoteId": "base", "notebookName": "Base", "notebookSyncStatus": 1,
          "bookTitle": "Book",
          "entries": [{
            "word": "alpha", "translation": "Alpha", "context": "Alpha context.",
            "explanation": null, "partOfSpeech": "noun", "bookTitle": "Book", "chapterTitle": null,
            "kgCardId": "card-alpha", "difficultyTier": "core", "reviewMode": "recognition",
            "reviewExamples": [], "collocations": null, "rootForm": null, "inflections": null,
            "syncStatus": 1, "actionType": "add", "isArchived": false,
            "reviewIntervalHours": 24, "nextReviewAt": "2099-01-01T00:00:00Z",
            "lastReviewedAt": null, "reviewCount": 0, "reviewStreak": 0,
            "lastReviewFeedbackRaw": -1, "graphLinksByKind": {}
          }],
          "entryOverrides": [],
          "reviewHistory": []
        },
        "p11.644.reviewMix": {
          "notebookRemoteId": "middle", "notebookName": "Middle", "notebookSyncStatus": 1,
          "bookTitle": "Book", "entries": [], "baseFixture": "vocabListLong",
          "entryOverrides": [{
            "word": "alpha",
            "reviewIntervalHours": 24, "nextReviewAt": 1799999940,
            "lastReviewedAt": "2026-08-12T00:00:00Z", "reviewCount": 3,
            "reviewStreak": 2, "lastReviewFeedbackRaw": 1
          }],
          "reviewHistory": []
        },
        "review.mixed": {
          "notebookRemoteId": "leaf", "notebookName": "Leaf", "notebookSyncStatus": 1,
          "bookTitle": "Book", "entries": [], "baseFixture": "p11.644.reviewMix",
          "entryOverrides": [],
          "reviewHistory": []
        }
      }
    }
    """

    private static let cyclicDataset = """
    {
      "schema": "kg.fixture.dataset.v2",
      "datasetID": "inheritance-cycle",
      "vocabulary": {
        "vocabListLong": {
          "notebookRemoteId": "a", "notebookName": "A", "notebookSyncStatus": 1,
          "bookTitle": "Book", "entries": [], "baseFixture": "p11.644.reviewMix",
          "entryOverrides": [], "reviewHistory": []
        },
        "p11.644.reviewMix": {
          "notebookRemoteId": "b", "notebookName": "B", "notebookSyncStatus": 1,
          "bookTitle": "Book", "entries": [], "baseFixture": "vocabListLong",
          "entryOverrides": [], "reviewHistory": []
        }
      }
    }
    """

    private static let duplicateOverrideAcrossInheritanceDataset = """
    {
      "schema": "kg.fixture.dataset.v2",
      "datasetID": "inheritance-duplicate-override",
      "vocabulary": {
        "vocabListLong": {
          "notebookRemoteId": "base", "notebookName": "Base", "notebookSyncStatus": 1,
          "bookTitle": "Book",
          "entries": [{
            "word": "alpha", "translation": "Alpha", "context": "Alpha context.",
            "explanation": null, "partOfSpeech": "noun", "bookTitle": "Book", "chapterTitle": null,
            "kgCardId": "card-alpha", "difficultyTier": "core", "reviewMode": "recognition",
            "reviewExamples": [], "collocations": null, "rootForm": null, "inflections": null,
            "syncStatus": 1, "actionType": "add", "isArchived": false,
            "reviewIntervalHours": 24, "nextReviewAt": "2099-01-01T00:00:00Z",
            "lastReviewedAt": null, "reviewCount": 0, "reviewStreak": 0,
            "lastReviewFeedbackRaw": -1, "graphLinksByKind": {}
          }],
          "entryOverrides": [{
            "word": "alpha",
            "reviewIntervalHours": 24, "nextReviewAt": "2099-01-01T00:00:00Z",
            "lastReviewedAt": null, "reviewCount": 1, "reviewStreak": 1,
            "lastReviewFeedbackRaw": 1
          }],
          "reviewHistory": []
        },
        "p11.644.reviewMix": {
          "notebookRemoteId": "child", "notebookName": "Child", "notebookSyncStatus": 1,
          "bookTitle": "Book", "entries": [], "baseFixture": "vocabListLong",
          "entryOverrides": [{
            "word": "alpha",
            "reviewIntervalHours": 48, "nextReviewAt": "2099-01-02T00:00:00Z",
            "lastReviewedAt": null, "reviewCount": 2, "reviewStreak": 2,
            "lastReviewFeedbackRaw": 1
          }],
          "reviewHistory": []
        }
      }
    }
    """

    private static let inheritedReviewHistoryDataset = """
    {
      "schema": "kg.fixture.dataset.v2",
      "datasetID": "inheritance-review-history",
      "vocabulary": {
        "vocabListLong": {
          "notebookRemoteId": "base", "notebookName": "Base", "notebookSyncStatus": 1,
          "bookTitle": "Book",
          "entries": [{
            "word": "alpha", "translation": "Alpha", "context": "Alpha context.",
            "explanation": null, "partOfSpeech": "noun", "bookTitle": "Book", "chapterTitle": null,
            "kgCardId": "card-alpha", "difficultyTier": "core", "reviewMode": "recognition",
            "reviewExamples": [], "collocations": null, "rootForm": null, "inflections": null,
            "syncStatus": 1, "actionType": "add", "isArchived": false,
            "reviewIntervalHours": 24, "nextReviewAt": "2099-01-01T00:00:00Z",
            "lastReviewedAt": null, "reviewCount": 0, "reviewStreak": 0,
            "lastReviewFeedbackRaw": -1, "graphLinksByKind": {}
          }],
          "entryOverrides": [], "reviewHistory": []
        },
        "p11.644.reviewMix": {
          "notebookRemoteId": "child", "notebookName": "Child", "notebookSyncStatus": 1,
          "bookTitle": "Book", "entries": [], "baseFixture": "vocabListLong",
          "entryOverrides": [],
          "reviewHistory": [{
            "word": "alpha", "feedback": 1, "reviewedAt": "2026-08-12T00:00:00Z"
          }]
        }
      }
    }
    """
}
#endif
