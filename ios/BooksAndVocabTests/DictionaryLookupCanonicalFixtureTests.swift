import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("P1/P2 canonical dictionary lookup", .serialized)
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
        #expect(coordinator.dictionaryMaterialization?.datasetSHA256 == "609f35f300df7a2d340f2799625b8ff50486bda835cafb05b72a6b7396abfced")
        #expect(coordinator.dictionaryMaterialization?.sourceAssetID == "catalog_reader_epub")
        #expect(coordinator.dictionaryMaterialization?.sourceAssetPath.hasSuffix("/ops/fixtures/assets/catalog-reader.epub") == true)
        #expect(coordinator.dictionaryMaterialization?.sourceAssetByteSize == 1690)
        #expect(coordinator.dictionaryMaterialization?.sourceAssetSHA256 == "4cfe357ba9c217fbfbe1af6b2831c69e0d476041267c99fae81ea5ba1967c3de")
    }

    @Test("KGService routes the P1 fixture source into AddLink state")
    func kgServiceRoutesP1FixtureIntoAddLinkState() async throws {
        let data = try Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json")
        let service = KGService()
        let coordinator = AddLinkCoordinator()

        // AddLinkCoordinator launches its lookup in a child task. Inject the
        // fixture through KGService's explicit DEBUG seam so this unit test
        // proves the service route without depending on TaskLocal inheritance
        // across that asynchronous boundary.
        service.fixtureDictionaryService = try FixtureDatasetStore.withTestingData(data) {
            try FixtureDictionaryServing.fromFixtureDatasetStore()
        }
        coordinator.submitSearch(query: "engraved", using: service)
        try await settle { coordinator.lookupState.isSuccess }

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
        let insertContext = ModelContext(container)
        insertContext.insert(source)
        try insertContext.save()

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
        let savedContext = ModelContext(container)
        let saved = try savedContext.fetch(FetchDescriptor<VocabularyEntry>())
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

    @Test("learning-card reuse accepts a nil dictionary projection without a dictionary-card fetch")
    func learningCardReuseDoesNotFetchDictionaryProjection() async throws {
        let base = try canonicalService()
        let service = LearningReuseDictionaryService(base: base)
        let coordinator = AddLinkCoordinator()
        let source = VocabularyEntry(
            word: "source", translation: "source", context: "", bookTitle: "Book"
        )
        source.kgCardId = "source-card"
        source.notebookId = "notebook"
        let existingLearning = VocabularyEntry(
            word: "engraved", translation: "already learned", context: "", bookTitle: "Book"
        )
        existingLearning.kgCardId = LearningReuseDictionaryService.learningCardID
        existingLearning.notebookId = "notebook"
        existingLearning.cardRole = .learning
        existingLearning.reviewEligible = true
        existingLearning.markSynced()
        let container = try Self.inMemoryContainer()
        let context = ModelContext(container)
        context.insert(source)
        context.insert(existingLearning)
        try context.save()

        coordinator.submitSearch(query: "engraved", using: base)
        try await settle { coordinator.lookupState.isSuccess }
        guard case .success(_, let entry?, _) = coordinator.lookupState else {
            Issue.record("expected canonical dictionary entry before learning-card reuse")
            return
        }

        await coordinator.materializeSelectedExample(
            sourceEntry: source,
            entry: entry,
            using: service,
            container: container
        )

        #expect(coordinator.materializePhase == .succeeded)
        #expect(await service.fetchCount == 0)
        #expect(source.graphLinksByKind["shares_usage"]?.first?.cardId == existingLearning.kgCardId)
        let saved = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        let reused = try #require(saved.first(where: { $0.kgCardId == existingLearning.kgCardId }))
        #expect(reused.cardRole == .learning)
        #expect(reused.dictionaryPayloadJSON == nil)
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

    @Test("an unregistered fixture query fails closed instead of falling back to result")
    func unknownFixtureQueryFailsClosed() async throws {
        let service = try canonicalService()

        do {
            _ = try await service.searchDictionary(
                query: "typo-state",
                sourceLanguage: "en",
                targetLanguage: "zh-Hant"
            )
            Issue.record("an unregistered fixture query must not fall back to result")
        } catch let error as FixtureDictionaryServing.FixtureError {
            guard case .unknownQuery(let query) = error else {
                Issue.record("expected unknownQuery, got \(error)")
                return
            }
            #expect(query == "typo-state")
        } catch {
            Issue.record("unexpected fixture query error: \(error)")
        }
    }

    @Test("P2 missing-example counterexample rejects the source before lookup")
    func p2MissingExampleCounterexampleFailsClosed() throws {
        let original = try Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json")
        var root = try #require(
            JSONSerialization.jsonObject(with: original, options: []) as? [String: Any]
        )
        var context = try #require(root["scenarioContext"] as? [String: Any])
        var dictionary = try #require(context["dictionary"] as? [String: Any])
        var examples = try #require(dictionary["examples"] as? [[String: Any]])
        examples.removeAll { $0["id"] as? String == "example-1" }
        dictionary["examples"] = examples
        context["dictionary"] = dictionary
        root["scenarioContext"] = context
        let malformed = try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])

        let counterexample = try #require(
            FixtureDatasetStore.withTestingData(original) {
                FixtureDatasetStore.dictionaryCounterexampleContract(for: .p2MissingExample)
            }
        )
        #expect(counterexample.fixtureID == "dictionary.p2.missing-example")
        #expect(throws: FixtureDictionaryServing.FixtureError.self) {
            try FixtureDatasetStore.withTestingData(malformed) {
                try FixtureDictionaryServing.fromFixtureDatasetStore(
                    fixtureID: .p2DictionarySenses
                )
            }
        }
    }

    @Test("P2 materialize-error counterexample rejects a missing projection")
    func p2MaterializeErrorCounterexampleFailsClosed() async throws {
        let data = try Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json")
        let counterexample = try #require(
            FixtureDatasetStore.withTestingData(data) {
                FixtureDatasetStore.dictionaryCounterexampleContract(for: .p2MaterializeError)
            }
        )
        #expect(counterexample.fixtureID == "dictionary.p2.materialize-error")

        let base = try canonicalService()
        let result = try await runMaterialization(
            lookupService: base,
            materializationService: MissingProjectionDictionaryService(base: base)
        )
        #expect(result.coordinator.materializePhase == .failed)
        #expect(result.source.graphLinksByKind["shares_usage"] == nil)
        let saved = try ModelContext(result.container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }) == nil)
    }

    @Test("fixture service creation rejects invalid source path, byte size, or hash")
    func fixtureServiceRejectsInvalidRuntimeProvenance() throws {
        let original = try Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json")
        let json = String(decoding: original, as: UTF8.self)
        let assetPath = "ops/fixtures/assets/catalog-reader.epub"
        let assetHash = "4cfe357ba9c217fbfbe1af6b2831c69e0d476041267c99fae81ea5ba1967c3de"
        let variants = [
            json.replacingOccurrences(of: assetPath, with: "definitely/missing/catalog-reader.epub"),
            json.replacingOccurrences(of: "\"byteSize\": 1690", with: "\"byteSize\": 1691"),
            json.replacingOccurrences(
                of: assetHash,
                with: String(repeating: "0", count: assetHash.count)
            ),
            json.replacingOccurrences(
                of: "\"exampleIDs\": [\n            \"example-1\"",
                with: "\"exampleIDs\": [\n            \"missing-example\""
            ),
        ]

        for variant in variants {
            #expect(throws: FixtureDictionaryServing.FixtureError.self) {
                try FixtureDatasetStore.withTestingData(Data(variant.utf8)) {
                    try FixtureDictionaryServing.fromFixtureDatasetStore()
                }
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
        let saved = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }) == nil)
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
        let saved = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }) == nil)
    }

    @Test("materialization rejects a same-ID projection link with wrong endpoints")
    func materializationRejectsProjectionLinkWithWrongEndpoints() async throws {
        let base = try canonicalService()
        let service = MalformedProjectionDictionaryService(
            base: base,
            corruption: .projectionOnly(.endpoints)
        )
        let result = try await runMaterialization(
            lookupService: base,
            materializationService: service
        )

        #expect(result.coordinator.materializePhase == .failed)
        #expect(result.source.graphLinksByKind.isEmpty)
        let saved = try ModelContext(result.container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }) == nil)
    }

    @Test("materialization rejects a same-ID projection link with wrong kind")
    func materializationRejectsProjectionLinkWithWrongKind() async throws {
        let base = try canonicalService()
        let service = MalformedProjectionDictionaryService(
            base: base,
            corruption: .projectionOnly(.kind)
        )
        let result = try await runMaterialization(
            lookupService: base,
            materializationService: service
        )

        #expect(result.coordinator.materializePhase == .failed)
        #expect(result.source.graphLinksByKind.isEmpty)
        let saved = try ModelContext(result.container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }) == nil)
    }

    @Test("materialization rejects equal wrong-endpoint links from response and projection")
    func materializationRejectsEqualWrongEndpointLinks() async throws {
        let base = try canonicalService()
        let service = MalformedProjectionDictionaryService(
            base: base,
            corruption: .responseAndProjection(.endpoints)
        )
        let result = try await runMaterialization(
            lookupService: base,
            materializationService: service
        )

        #expect(result.coordinator.materializePhase == .failed)
        #expect(result.source.graphLinksByKind.isEmpty)
        let saved = try ModelContext(result.container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }) == nil)
    }

    @Test("materialization rejects equal wrong-kind links from response and projection")
    func materializationRejectsEqualWrongKindLinks() async throws {
        let base = try canonicalService()
        let service = MalformedProjectionDictionaryService(
            base: base,
            corruption: .responseAndProjection(.kind)
        )
        let result = try await runMaterialization(
            lookupService: base,
            materializationService: service
        )

        #expect(result.coordinator.materializePhase == .failed)
        #expect(result.source.graphLinksByKind.isEmpty)
        let saved = try ModelContext(result.container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(saved.first(where: { $0.kgCardId == "fixture-dictionary-card" }) == nil)
    }

    @Test("detached source is rejected before request, target, or graph mutation")
    func detachedSourceIsRejectedBeforeAnyMutation() async throws {
        let base = try canonicalService()
        let service = CountingMaterializationDictionaryService(base: base)
        let coordinator = AddLinkCoordinator()
        let detached = VocabularyEntry(
            word: "source", translation: "source", context: "", bookTitle: "Book"
        )
        detached.kgCardId = "source-card"
        detached.notebookId = "notebook"
        let container = try Self.inMemoryContainer()

        coordinator.submitSearch(query: "engraved", using: base)
        try await settle { coordinator.lookupState.isSuccess }
        guard case .success(_, let entry?, _) = coordinator.lookupState else {
            Issue.record("expected canonical dictionary entry before detached-source regression")
            return
        }

        await coordinator.materializeSelectedExample(
            sourceEntry: detached,
            entry: entry,
            using: service,
            container: container
        )

        #expect(coordinator.materializePhase == .failed)
        #expect(await service.requests.isEmpty)
        #expect(detached.graphLinksByKind.isEmpty)
        #expect(try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>()).isEmpty)
    }

    @Test("detached source manual link is rejected before placeholder or request")
    func detachedSourceManualLinkIsRejectedBeforeAnyMutation() async throws {
        let coordinator = AddLinkCoordinator()
        let detached = VocabularyEntry(
            word: "source", translation: "source", context: "", bookTitle: "Book"
        )
        detached.kgCardId = "source-card"
        detached.notebookId = "notebook"
        let target = VocabularyEntry(
            word: "target", translation: "target", context: "", bookTitle: "Book"
        )
        target.kgCardId = "target-card"
        target.notebookId = "notebook"
        let service = CountingGraphService()

        await coordinator.linkExisting(target: target, sourceEntry: detached, using: service)

        #expect(coordinator.materializePhase == .failed)
        #expect(coordinator.materializeFailure == .malformed)
        #expect(await service.requests.isEmpty)
        #expect(detached.graphLinksByKind.isEmpty)
        #expect(target.graphLinksByKind.isEmpty)
    }

    private func runMaterialization(
        lookupService: any DictionaryServing,
        materializationService: any DictionaryServing
    ) async throws -> (
        coordinator: AddLinkCoordinator,
        source: VocabularyEntry,
        container: ModelContainer
    ) {
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

        coordinator.submitSearch(query: "engraved", using: lookupService)
        try await settle { coordinator.lookupState.isSuccess }
        guard case .success(_, let entry?, _) = coordinator.lookupState else {
            throw FixtureDictionaryServing.FixtureError.missingCanonicalDictionary
        }

        await coordinator.materializeSelectedExample(
            sourceEntry: source,
            entry: entry,
            using: materializationService,
            container: container
        )
        return (coordinator, source, container)
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

private enum ProjectionLinkMutation: Sendable {
    case endpoints
    case kind
}

private enum ProjectionLinkCorruption: Sendable {
    case projectionOnly(ProjectionLinkMutation)
    case responseAndProjection(ProjectionLinkMutation)
}

private func corruptProjectionLink(
    _ link: KGGraphLink,
    mutation: ProjectionLinkMutation
) -> KGGraphLink {
    switch mutation {
    case .endpoints:
        return KGGraphLink(
            id: link.id,
            fromId: "wrong-source-card",
            toId: "wrong-target-card",
            kind: link.kind,
            confidence: link.confidence,
            reason: link.reason
        )
    case .kind:
        return KGGraphLink(
            id: link.id,
            fromId: link.fromId,
            toId: link.toId,
            kind: "related",
            confidence: link.confidence,
            reason: link.reason
        )
    }
}

private actor MalformedProjectionDictionaryService: DictionaryServing {
    let base: FixtureDictionaryServing
    let corruption: ProjectionLinkCorruption

    init(base: FixtureDictionaryServing, corruption: ProjectionLinkCorruption) {
        self.base = base
        self.corruption = corruption
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
        let mutation: ProjectionLinkMutation
        let mutateResponse: Bool
        switch corruption {
        case .projectionOnly(let value):
            mutation = value
            mutateResponse = false
        case .responseAndProjection(let value):
            mutation = value
            mutateResponse = true
        }
        let links = projection.links.map { link -> KGGraphLink in
            guard link.id == response.link.id else { return link }
            return corruptProjectionLink(link, mutation: mutation)
        }
        let malformedProjection = KGDictionaryCardProjection(
            card: projection.card,
            dictionaryEntry: projection.dictionaryEntry,
            selectedSenseKey: projection.selectedSenseKey,
            selectedExampleKey: projection.selectedExampleKey,
            materializationStatus: projection.materializationStatus,
            promotionErrorCode: projection.promotionErrorCode,
            promotionRetryable: projection.promotionRetryable,
            links: links
        )
        return DictionaryMaterializeLinkResponse(
            targetCard: response.targetCard,
            dictionaryCard: malformedProjection,
            link: mutateResponse
                ? corruptProjectionLink(response.link, mutation: mutation)
                : response.link,
            createdCard: response.createdCard,
            createdLink: response.createdLink,
            replayed: response.replayed
        )
    }
}

private actor CountingMaterializationDictionaryService: DictionaryServing {
    let base: FixtureDictionaryServing
    private(set) var requests: [DictionaryMaterializeLinkRequest] = []

    init(base: FixtureDictionaryServing) {
        self.base = base
    }

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest,
        idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        requests.append(request)
        return try await base.materializeDictionaryLink(
            request: request,
            idempotencyKey: idempotencyKey
        )
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

private actor LearningReuseDictionaryService: DictionaryServing {
    static let learningCardID = "fixture-learning-card"

    let base: FixtureDictionaryServing
    private(set) var fetchCount = 0

    init(base: FixtureDictionaryServing) {
        self.base = base
    }

    func searchDictionary(
        query: String,
        sourceLanguage: String,
        targetLanguage: String
    ) async throws -> DictionarySearchResponse {
        try await base.searchDictionary(
            query: query,
            sourceLanguage: sourceLanguage,
            targetLanguage: targetLanguage
        )
    }

    func fetchDictionaryEntry(
        provider: String,
        entryKey: String,
        targetLanguage: String
    ) async throws -> DictionaryEntryResponse {
        try await base.fetchDictionaryEntry(
            provider: provider,
            entryKey: entryKey,
            targetLanguage: targetLanguage
        )
    }

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest,
        idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        let response = try await base.materializeDictionaryLink(
            request: request,
            idempotencyKey: idempotencyKey
        )
        let targetCard = try Self.learningCard(notebookID: request.notebookId)
        let link = KGGraphLink(
            id: response.link.id,
            fromId: response.link.fromId,
            toId: targetCard.id,
            kind: response.link.kind,
            confidence: response.link.confidence,
            reason: response.link.reason
        )
        return DictionaryMaterializeLinkResponse(
            targetCard: targetCard,
            dictionaryCard: nil,
            link: link,
            createdCard: false,
            createdLink: response.createdLink,
            replayed: response.replayed
        )
    }

    func fetchDictionaryCard(cardId: String) async throws -> KGDictionaryCardProjection {
        fetchCount += 1
        throw FixtureDictionaryServing.FixtureError.unavailable(fixtureID: cardId)
    }

    private static func learningCard(notebookID: String) throws -> KGCard {
        try JSONDecoder().decode(
            KGCard.self,
            from: Data(
                """
                {
                  "id": "\(learningCardID)",
                  "content": "engraved",
                  "meaning": "already learned",
                  "pos": "verb",
                  "examples": ["The artist engraved the glass."],
                  "mode": "recognition",
                  "isDeleted": false,
                  "isArchived": false,
                  "notebookId": "\(notebookID)",
                  "cardRole": "learning",
                  "reviewEligible": true,
                  "readerHidden": false,
                  "promotionState": "idle"
                }
                """.utf8
            )
        )
    }
}

private actor CountingGraphService: GraphServing {
    private(set) var requests: [(fromID: String, toID: String, notebookID: String)] = []

    func pullGraphLinks() async throws -> [KGGraphLink] { [] }

    func createManualLink(
        fromId: String,
        toId: String,
        notebookId: String
    ) async throws -> KGGraphLink {
        requests.append((fromId, toId, notebookId))
        throw FixtureDictionaryServing.FixtureError.unavailable(fixtureID: "manual-link")
    }

    func deleteLink(linkId: String, notebookId: String) async throws {}

    func hideLink(linkId: String, notebookId: String) async throws {}

    func unhideLink(linkId: String, notebookId: String) async throws {}
}
