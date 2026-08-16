import CryptoKit
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

struct VocabularyEntrySchemaMigrationTests {
    private struct FixtureProvenance: Decodable {
        struct Row: Decodable {
            let word: String
            let syncStatus: Int
            let actionType: String
            let classification: String
        }

        let schema: String
        let sourceCommit: String
        let sourceBuild: Int
        let storeSHA256: String
        let rows: [Row]
    }

    private static let fixtureDirectory = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .appendingPathComponent("Fixtures/VocabularyEntryBuild9", isDirectory: true)

    private static func removeStoreArtifacts(at storeURL: URL) {
        for artifactURL in AppBootstrap.storeArtifactURLs(for: storeURL) {
            try? FileManager.default.removeItem(at: artifactURL)
        }
    }

    private static func copyFixture(to destinationURL: URL) throws {
        for sourceURL in AppBootstrap.storeArtifactURLs(
            for: fixtureDirectory.appendingPathComponent("LocalStore.store")
        ) where FileManager.default.fileExists(atPath: sourceURL.path) {
            let suffix = String(sourceURL.path.dropFirst(
                fixtureDirectory.appendingPathComponent("LocalStore.store").path.count
            ))
            let destinationArtifact = URL(fileURLWithPath: destinationURL.path + suffix)
            try FileManager.default.copyItem(at: sourceURL, to: destinationArtifact)
        }
    }

    private static func currentContainer(at storeURL: URL) throws -> ModelContainer {
        let schema = Schema([
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            PodcastSeries.self,
            PodcastEpisode.self,
            SharedDeck.self,
        ])
        let configuration = ModelConfiguration(
            "LocalStore",
            schema: schema,
            url: storeURL,
            cloudKitDatabase: .none
        )
        return try ModelContainer(for: schema, configurations: configuration)
    }

    @Test @MainActor func build9StoreMigratesWithoutLosingOrdinaryOrPendingCards() throws {
        let fixtureStoreURL = Self.fixtureDirectory.appendingPathComponent("LocalStore.store")
        let fixtureDigest = SHA256.hash(data: try Data(contentsOf: fixtureStoreURL))
            .map { String(format: "%02x", $0) }
            .joined()
        let provenanceURL = Self.fixtureDirectory.appendingPathComponent("provenance.json")
        let provenance = try JSONDecoder().decode(
            FixtureProvenance.self,
            from: Data(contentsOf: provenanceURL)
        )
        #expect(provenance.schema == "kg.ios.vocabulary-schema-fixture.v1")
        #expect(provenance.sourceCommit == "0c3bec76d")
        #expect(provenance.sourceBuild == 9)
        #expect(fixtureDigest == provenance.storeSHA256, "frozen build 9 store must not drift")
        #expect(provenance.rows.count == 2)
        #expect(provenance.rows.allSatisfy { $0.classification == "ordinary" })
        #expect(provenance.rows.first { $0.word == "legacy-synced" }?.syncStatus == 1)
        #expect(provenance.rows.first { $0.word == "legacy-pending" }?.syncStatus == 0)
        #expect(provenance.rows.allSatisfy { $0.actionType == "add" })

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocabulary-schema-migration-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let storeURL = directory.appendingPathComponent("LocalStore.store")
        defer {
            Self.removeStoreArtifacts(at: storeURL)
            try? FileManager.default.removeItem(at: directory)
        }
        try Self.copyFixture(to: storeURL)

        do {
            let container = try Self.currentContainer(at: storeURL)
            let entries = try container.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
            #expect(entries.count == 2)

            let synced = try #require(entries.first { $0.word == "legacy-synced" })
            #expect(synced.id == UUID(uuidString: "11111111-1111-1111-1111-111111111111"))
            #expect(synced.translation == "保留的翻譯")
            #expect(synced.context == "preserved context")
            #expect(synced.explanation == "preserved explanation")
            #expect(synced.partOfSpeech == "noun")
            #expect(synced.rootForm == "legacy")
            #expect(synced.inflections == ["legacy", "legacies"])
            #expect(synced.syncStatus == 1)
            #expect(synced.kgCardId == "kg-legacy-synced")
            #expect(synced.actionType == "add")
            #expect(synced.reviewExamples == ["Preserved example."])
            #expect(synced.collocations == ["legacy system"])
            #expect(synced.reviewIntervalHours == 72)
            #expect(synced.reviewCount == 4)
            #expect(synced.lapseCount == 1)
            #expect(synced.reviewStreak == 2)
            #expect(synced.notebookId == "migration-notebook")

            let pending = try #require(entries.first { $0.word == "legacy-pending" })
            #expect(pending.syncStatus == 0)
            #expect(pending.actionType == "add")
            #expect(pending.kgCardId == nil)
            #expect(pending.translation == "尚未上傳")

            #expect(try container.mainContext.fetchCount(FetchDescriptor<Notebook>()) == 1)
            #expect(try container.mainContext.fetchCount(FetchDescriptor<ReviewRecord>()) == 1)
        }

        let reopened = try Self.currentContainer(at: storeURL)
        let reopenedEntries = try reopened.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(reopenedEntries.map(\.word).sorted() == ["legacy-pending", "legacy-synced"])
        #expect(reopenedEntries.first { $0.word == "legacy-pending" }?.syncStatus == 0)
    }
}
