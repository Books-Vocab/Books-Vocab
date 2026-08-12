import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("P1 canonical dictionary lookup", .serialized)
@MainActor
struct DictionaryLookupCanonicalFixtureTests {
    @Test("lookup consumes canonical senses, provenance, and materialization")
    func lookupConsumesCanonicalPayload() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "engraved", using: service)
        try await settle { coordinator.lookupState.isSuccess }

        guard case .success(_, let entry?, let cacheStatus) = coordinator.lookupState else {
            Issue.record("expected canonical dictionary result")
            return
        }
        #expect(cacheStatus == "fixture")
        #expect(entry.provider == "fixture")
        #expect(entry.entryKey == "engraved")
        #expect(entry.senses.map(\.id) == ["sense-1", "sense-2"])
        #expect(entry.senses.flatMap(\.examples).map(\.id) == ["example-1", "example-2"])
        #expect(entry.attributionText == "canonical dictionary fixture")
        #expect(coordinator.selectedSenseKey == "sense-1")
        #expect(coordinator.selectedExampleKey == "example-1")
        #expect(coordinator.selectedMaterialization?.provenance.provider == "fixture")
        #expect(coordinator.selectedMaterialization?.provenance.attributionText == "canonical dictionary fixture")
        #expect(coordinator.dictionaryMaterialization?.status == "ready")
        #expect(coordinator.dictionaryMaterialization?.selectedSenseID == "sense-1")
        #expect(coordinator.dictionaryMaterialization?.selectedExampleID == "example-1")
        #expect(coordinator.dictionaryMaterialization?.sourceFixtureID == "dictionary.lookup.result")
    }

    @Test("KGService routes the P1 fixture source into AddLink state")
    func kgServiceRoutesP1FixtureIntoAddLinkState() async throws {
        let data = try Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json")
        let service = KGService()
        let coordinator = AddLinkCoordinator()

        try await FixtureDatasetStore.withTestingData(data) {
            coordinator.submitSearch(query: "engraved", using: service)
            try await settle { coordinator.lookupState.isSuccess }
        }

        guard case .success(let query, let entry?, let cacheStatus) = coordinator.lookupState else {
            Issue.record("expected KGService to consume the P1 canonical dictionary fixture")
            return
        }
        #expect(query == "engraved")
        #expect(entry.entryKey == "engraved")
        #expect(cacheStatus == "fixture")
        #expect(coordinator.selectedSenseKey == "sense-1")
        #expect(coordinator.selectedExampleKey == "example-1")
    }

    @Test("ready canonical materialization completes without a synthetic response")
    func readyCanonicalMaterializationCompletes() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()
        let source = VocabularyEntry(
            word: "source", translation: "source", context: "", bookTitle: "Book"
        )
        source.kgCardId = "source-card"
        source.notebookId = "notebook"
        let container = try Self.inMemoryContainer()

        coordinator.submitSearch(query: "engraved", using: service)
        try await settle { coordinator.lookupState.isSuccess }
        guard case .success(_, let entry?, _) = coordinator.lookupState else {
            Issue.record("expected canonical dictionary entry before materialization")
            return
        }

        await coordinator.materializeSelectedExample(
            sourceEntry: source,
            entry: entry,
            using: service,
            container: container
        )

        #expect(coordinator.materializePhase == .succeeded)
    }

    private func canonicalService() throws -> FixtureDictionaryServing {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json"))
        return try FixtureDatasetStore.withTestingData(data) {
            try FixtureDictionaryServing.fromFixtureDatasetStore()
        }
    }

    private static func data(at relativePath: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent(relativePath))
    }

    private static func inMemoryContainer() throws -> ModelContainer {
        let schema = Schema([VocabularyEntry.self, ReviewRecord.self])
        let configuration = ModelConfiguration(
            isStoredInMemoryOnly: true,
            cloudKitDatabase: .none
        )
        return try ModelContainer(for: schema, configurations: [configuration])
    }

    private func settle(
        _ predicate: @escaping @MainActor () -> Bool
    ) async throws {
        for _ in 0..<150 {
            if predicate() { return }
            await Task.yield()
            try await Task.sleep(for: .milliseconds(2))
        }
        Issue.record("timed out waiting for state transition")
    }
}
