import Foundation
import Testing
@testable import BooksAndVocab

@Suite("P1 dictionary lookup state flow", .serialized)
@MainActor
struct DictionaryLookupStateFlowTests {
    @Test("detail failure preserves the search hit as a partial state")
    func detailFailureIsPartial() async throws {
        let service = P1DictionaryService(outcomes: [.partialOffline])
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: " lucid ", using: service)
        try await settle { coordinator.lookupState.isPartial }

        guard case .partial(let query, let hit, let failure) = coordinator.lookupState else {
            Issue.record("expected a partial lookup state")
            return
        }
        #expect(query == "lucid")
        #expect(hit.entryKey == "en.bHVjaWQ")
        #expect(failure == .offline)
    }

    @Test("retry is an observable state before the request resolves")
    func retryIsObservable() async throws {
        let service = P1DictionaryService(outcomes: [.offline, .success])
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "lucid", using: service)
        try await settle { coordinator.lookupState == .offline(query: "lucid") }

        coordinator.retrySearch(using: service)
        #expect(coordinator.lookupState == .retry(query: "lucid", attempt: 1))
        try await settle { coordinator.lookupState.isSuccess }
    }

    @Test("selected sense example and provenance are observable materialization data")
    func selectionMaterializationIsObservable() async throws {
        let service = P1DictionaryService(outcomes: [.success])
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "lucid", using: service)
        try await settle { coordinator.lookupState.isSuccess }
        coordinator.select(senseKey: "sense_2", exampleKey: "example_2")

        #expect(coordinator.selectedMaterialization?.sense.id == "sense_2")
        #expect(coordinator.selectedMaterialization?.example.id == "example_2")
        #expect(coordinator.selectedMaterialization?.provenance.provider == "free_dictionary")
    }

    private static func settle(
        _ predicate: @escaping @MainActor () -> Bool
    ) async throws {
        for _ in 0..<100 {
            if predicate() { return }
            await Task.yield()
            try await Task.sleep(for: .milliseconds(2))
        }
        Issue.record("timed out waiting for state transition")
    }
}

private actor P1DictionaryService: DictionaryServing {
    enum Outcome {
        case partialOffline
        case offline
        case success
    }

    private var outcomes: [Outcome]
    private var detailOutcome: Outcome = .success

    init(outcomes: [Outcome]) {
        self.outcomes = outcomes
    }

    func searchDictionary(
        query: String,
        sourceLanguage: String,
        targetLanguage: String
    ) async throws -> DictionarySearchResponse {
        let outcome = outcomes.first ?? .success
        if !outcomes.isEmpty { outcomes.removeFirst() }
        switch outcome {
        case .partialOffline, .success:
            switch outcome {
            case .partialOffline: detailOutcome = .partialOffline
            case .success: detailOutcome = .success
            case .offline: break
            }
            return try Self.searchResponse()
        case .offline:
            throw KGError.offline
        }
    }

    func fetchDictionaryEntry(
        provider: String,
        entryKey: String,
        targetLanguage: String
    ) async throws -> DictionaryEntryResponse {
        switch detailOutcome {
        case .partialOffline, .offline:
            throw KGError.offline
        case .success:
            return try Self.entryResponse()
        }
    }

    private static func searchResponse() throws -> DictionarySearchResponse {
        try JSONDecoder().decode(
            DictionarySearchResponse.self,
            from: Data(DictionaryPhase2ATests.searchJSON.utf8)
        )
    }

    private static func entryResponse() throws -> DictionaryEntryResponse {
        let entry = try JSONDecoder().decode(
            LexicalEntry.self,
            from: Data(DictionaryPhase2BTests.lexicalJSON.utf8)
        )
        return DictionaryEntryResponse(entry: entry, cacheStatus: "fresh")
    }
}
