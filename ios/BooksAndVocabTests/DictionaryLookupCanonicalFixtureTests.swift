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
        #expect(coordinator.dictionaryMaterialization?.datasetID == "marketing_demo")
        #expect(coordinator.dictionaryMaterialization?.datasetSHA256 == "986c04b5219bfa9c9a5f3922864f42034081cbd90939db4353de8160656e6bd0")
        #expect(coordinator.dictionaryMaterialization?.sourceAssetID == "catalog_reader_epub")
        #expect(coordinator.dictionaryMaterialization?.sourceAssetSHA256 == "4cfe357ba9c217fbfbe1af6b2831c69e0d476041267c99fae81ea5ba1967c3de")
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

    @Test("fixture materialization calls the service and persists the graph projection")
    func fixtureMaterializationCallsServiceAndPersistsGraphProjection() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()
        let source = VocabularyEntry(
            word: "source", translation: "source", context: "", bookTitle: "Book"
        )
        source.kgCardId = "source-card"
        source.notebookId = "notebook"
        let container = try Self.inMemoryContainer()
        let context = ModelContext(container)
        context.insert(source)
        try context.save()

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
        #expect(await service.materializationRequests.count == 1)
        let context = ModelContext(container)
        let saved = try context.fetch(FetchDescriptor<VocabularyEntry>())
        let sourceAfterMaterialization = try #require(saved.first(where: { $0.kgCardId == "source-card" }))
        #expect(sourceAfterMaterialization.graphLinksByKind["shares_usage"]?.count == 1)
        #expect(sourceAfterMaterialization.graphLinksByKind["shares_usage"]?.first?.cardId == "fixture-dictionary-card")
        #expect(sourceAfterMaterialization.dictionarySelectedSenseKey == nil)
        let dictionaryCard = try #require(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }))
        #expect(dictionaryCard.cardRole == .dictionary)
        #expect(dictionaryCard.dictionarySelectedSenseKey == "sense-1")
        #expect(dictionaryCard.dictionarySelectedExampleKey == "example-1")
        #expect(dictionaryCard.graphLinksByKind["shares_usage"]?.count == 1)
        #expect(dictionaryCard.graphLinksByKind["shares_usage"]?.first?.cardId == "source-card")
    }

    @Test("invalid fixture-driven dictionary lookup fails closed instead of using network")
    func invalidFixtureDrivenLookupFailsClosed() async throws {
        let service = KGService()
        try await FixtureDatasetStore.withTestingData(Data("not-json".utf8)) {
            do {
                _ = try await service.searchDictionary(query: "engraved")
                Issue.record("invalid UI World must not fall through to network dictionary lookup")
            } catch is FixtureDictionaryServing.FixtureError {
                // Expected: fixture-driven runs are fail-closed.
            } catch {
                Issue.record("unexpected error for invalid fixture: \(error)")
            }
        }
    }

    @Test("absent fixture-driven dictionary lookup fails closed instead of using network")
    func absentFixtureDrivenLookupFailsClosed() async throws {
        let service = KGService()
        try await FixtureDatasetStore.withTestingData(nil) {
            do {
                _ = try await service.searchDictionary(query: "engraved")
                Issue.record("fixture-driven run without a UI World must not use network dictionary lookup")
            } catch let error as FixtureDictionaryServing.FixtureError {
                guard case .unavailable(let fixtureID) = error else {
                    Issue.record("expected unavailable fixture error, got \(error)")
                    return
                }
                #expect(fixtureID == "ui-p1-dictionary-rich")
            } catch {
                Issue.record("unexpected error for absent fixture: \(error)")
            }
        }
    }

    @Test("materialization fails closed when the dictionary projection cannot be read back")
    func materializationFailsClosedWhenProjectionCannotBeReadBack() async throws {
        let base = try canonicalService()
        let service = MissingProjectionDictionaryService(base: base)
        let coordinator = AddLinkCoordinator()
        let source = VocabularyEntry(
            word: "source", translation: "source", context: "", bookTitle: "Book"
        )
        source.kgCardId = "source-card"
        source.notebookId = "notebook"
        let container = try Self.inMemoryContainer()
        let context = ModelContext(container)
        context.insert(source)
        try context.save()

        coordinator.submitSearch(query: "engraved", using: base)
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

        #expect(coordinator.materializePhase == .failed)
        #expect(source.graphLinksByKind["shares_usage"] == nil)
    }

    @Test("materialization fails closed when the projection omits the graph link")
    func materializationFailsClosedWhenProjectionOmitsGraphLink() async throws {
        let base = try canonicalService()
        let service = MissingGraphLinkDictionaryService(base: base)
        let coordinator = AddLinkCoordinator()
        let source = VocabularyEntry(
            word: "source", translation: "source", context: "", bookTitle: "Book"
        )
        source.kgCardId = "source-card"
        source.notebookId = "notebook"
        let container = try Self.inMemoryContainer()
        let context = ModelContext(container)
        context.insert(source)
        try context.save()

        coordinator.submitSearch(query: "engraved", using: base)
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

        #expect(coordinator.materializePhase == .failed)
        #expect(source.graphLinksByKind["shares_usage"] == nil)
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

private actor MissingProjectionDictionaryService: DictionaryServing {
    let base: FixtureDictionaryServing

    init(base: FixtureDictionaryServing) {
        self.base = base
    }

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest,
        idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        let response = try await base.materializeDictionaryLink(
            request: request,
            idempotencyKey: idempotencyKey
        )
        return DictionaryMaterializeLinkResponse(
            targetCard: response.targetCard,
            dictionaryCard: nil,
            link: response.link,
            createdCard: response.createdCard,
            createdLink: response.createdLink,
            replayed: response.replayed
        )
    }

    func fetchDictionaryCard(cardId: String) async throws -> KGDictionaryCardProjection {
        throw FixtureDictionaryServing.FixtureError.unavailable(fixtureID: cardId)
    }
}

private actor MissingGraphLinkDictionaryService: DictionaryServing {
    let base: FixtureDictionaryServing

    init(base: FixtureDictionaryServing) {
        self.base = base
    }

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest,
        idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        let response = try await base.materializeDictionaryLink(
            request: request,
            idempotencyKey: idempotencyKey
        )
        guard let projection = response.dictionaryCard else {
            throw FixtureDictionaryServing.FixtureError.missingCanonicalDictionary
        }
        let missingLinkProjection = KGDictionaryCardProjection(
            card: projection.card,
            dictionaryEntry: projection.dictionaryEntry,
            selectedSenseKey: projection.selectedSenseKey,
            selectedExampleKey: projection.selectedExampleKey,
            materializationStatus: projection.materializationStatus,
            promotionErrorCode: projection.promotionErrorCode,
            promotionRetryable: projection.promotionRetryable,
            links: []
        )
        return DictionaryMaterializeLinkResponse(
            targetCard: response.targetCard,
            dictionaryCard: missingLinkProjection,
            link: response.link,
            createdCard: response.createdCard,
            createdLink: response.createdLink,
            replayed: response.replayed
        )
    }
}
