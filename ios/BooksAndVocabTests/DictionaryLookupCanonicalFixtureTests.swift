import Foundation
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
