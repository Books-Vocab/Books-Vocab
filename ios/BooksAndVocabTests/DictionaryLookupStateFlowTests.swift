import Foundation
import Testing
@testable import BooksAndVocab

@Suite("P1 dictionary lookup state flow", .serialized)
@MainActor
struct DictionaryLookupStateFlowTests {
    @Test("empty result is observable from the canonical result state")
    func emptyResultIsObservable() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "empty", using: service)
        try await settle { coordinator.lookupState == .success(query: "empty", entry: nil, cacheStatus: "fixture") }

        #expect(coordinator.searchPhase == .empty)
    }

    @Test("loading remains live until the canonical request resolves")
    func loadingStateIsObservable() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "loading", using: service)
        #expect(coordinator.lookupState == .loading(query: "loading"))
        #expect(coordinator.searchPhase == .loading)
        coordinator.cancelSearch()
    }

    @Test("legacy search phase is a projection of canonical lookup state")
    func legacySearchPhaseCannotDriftFromLookupState() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        #expect(coordinator.searchPhase == .idle)
        coordinator.submitSearch(query: "loading", using: service)
        #expect(coordinator.lookupState == .loading(query: "loading"))
        #expect(coordinator.searchPhase == .loading)

        coordinator.cancelSearch()
        #expect(coordinator.lookupState == .idle)
        #expect(coordinator.searchPhase == .idle)

        coordinator.submitSearch(query: "empty", using: service)
        try await settle {
            coordinator.lookupState == .success(query: "empty", entry: nil, cacheStatus: "fixture")
        }
        #expect(coordinator.searchPhase == .empty)
    }

    @Test("detail failure preserves the canonical search hit as partial")
    func detailFailureIsPartial() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "partial", using: service)
        try await settle { coordinator.lookupState.isPartial }

        guard case .partial(let query, let hit, let failure) = coordinator.lookupState else {
            Issue.record("expected a partial lookup state")
            return
        }
        #expect(query == "partial")
        #expect(hit.entryKey == "engraved")
        #expect(failure == .offline)
    }

    @Test("offline and error states keep distinct live selectors")
    func offlineAndErrorStatesRemainDistinct() async throws {
        let offlineService = try canonicalService()
        let offlineCoordinator = AddLinkCoordinator()
        offlineCoordinator.submitSearch(query: "offline", using: offlineService)
        try await settle { offlineCoordinator.lookupState.isOffline }
        #expect(offlineCoordinator.lookupFailure(for: offlineCoordinator.lookupState) == .offline)

        let errorService = try canonicalService()
        let errorCoordinator = AddLinkCoordinator()
        errorCoordinator.submitSearch(query: "error", using: errorService)
        try await settle {
            if case .error = errorCoordinator.lookupState { return true }
            return false
        }
        #expect(errorCoordinator.lookupFailure(for: errorCoordinator.lookupState) == .unavailable)
    }

    @Test("retry is an observable state before the canonical request resolves")
    func retryIsObservable() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "retry", using: service)
        try await settle { coordinator.lookupState == .offline(query: "retry") }

        coordinator.retrySearch(using: service)
        #expect(coordinator.lookupState == .retry(query: "retry", attempt: 1))
        try await settle { coordinator.lookupState.isSuccess }
    }

    @Test("retry stays gated until the test continuation releases the canonical request")
    func retryWaitsForTestControlledRelease() async throws {
        let gate = DictionaryRetryGate()
        let service = try canonicalService(retryGate: gate)
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "retry", using: service)
        try await settle { coordinator.lookupState == .offline(query: "retry") }

        coordinator.retrySearch(using: service)
        #expect(coordinator.lookupState == .retry(query: "retry", attempt: 1))
        try await settleUntilGateIsWaiting(gate)
        #expect(coordinator.lookupState == .retry(query: "retry", attempt: 1))

        await gate.release()
        try await settle { coordinator.lookupState.isSuccess }
    }

    @Test("cancelling a gated retry cannot poison the newer generation")
    func cancelledGatedRetryCannotWinNewerGeneration() async throws {
        let gate = DictionaryRetryGate()
        let service = try canonicalService(retryGate: gate)
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "retry", using: service)
        try await settle { coordinator.lookupState == .offline(query: "retry") }
        coordinator.retrySearch(using: service)
        try await settleUntilGateIsWaiting(gate)

        coordinator.submitSearch(query: "engraved", using: service)
        try await settle { coordinator.lookupState.isSuccess }
        await gate.release()

        guard case .success(let query, let entry?, _) = coordinator.lookupState else {
            Issue.record("expected the newer dictionary lookup to succeed")
            return
        }
        #expect(query == "engraved")
        #expect(entry.entryKey == "engraved")
    }

    @Test("a cancelled loading fixture cannot win a newer lookup")
    func cancelledLoadingFixtureCannotWinNewerLookup() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "loading", using: service)
        coordinator.submitSearch(query: "engraved", using: service)
        try await settle { coordinator.lookupState.isSuccess }

        guard case .success(let query, let entry?, _) = coordinator.lookupState else {
            Issue.record("expected the newer dictionary lookup to succeed")
            return
        }
        #expect(query == "engraved")
        #expect(entry.entryKey == "engraved")
    }

    @Test("a cancelled partial fixture cannot poison a newer lookup")
    func cancelledPartialFixtureCannotPoisonNewerLookup() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "partial", using: service)
        coordinator.submitSearch(query: "engraved", using: service)
        try await settle { coordinator.lookupState.isSuccess }

        guard case .success(let query, let entry?, _) = coordinator.lookupState else {
            Issue.record("expected the newer dictionary lookup to succeed")
            return
        }
        #expect(query == "engraved")
        #expect(entry.entryKey == "engraved")
    }

    @Test("selected sense example and provenance are canonical materialization data")
    func selectionMaterializationIsObservable() async throws {
        let service = try canonicalService()
        let coordinator = AddLinkCoordinator()

        coordinator.submitSearch(query: "engraved", using: service)
        try await settle { coordinator.lookupState.isSuccess }
        coordinator.select(senseKey: "sense-2", exampleKey: "example-2")

        #expect(coordinator.selectedMaterialization?.sense.id == "sense-2")
        #expect(coordinator.selectedMaterialization?.example.id == "example-2")
        #expect(coordinator.selectedMaterialization?.provenance.provider == "fixture")
        #expect(coordinator.selectedMaterialization?.provenance.attributionText == "canonical dictionary fixture")
    }

    private func canonicalService(
        retryGate: DictionaryRetryGate? = nil
    ) throws -> FixtureDictionaryServing {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json"))
        return try FixtureDatasetStore.withTestingData(data) {
            try FixtureDictionaryServing.fromFixtureDatasetStore(retryGate: retryGate)
        }
    }

    private func settleUntilGateIsWaiting(_ gate: DictionaryRetryGate) async throws {
        for _ in 0..<200 {
            if await gate.isWaiting() { return }
            await Task.yield()
            try await Task.sleep(for: .milliseconds(2))
        }
        Issue.record("timed out waiting for retry continuation gate")
    }

    private func settle(
        _ predicate: @escaping @MainActor () -> Bool
    ) async throws {
        for _ in 0..<200 {
            if predicate() { return }
            await Task.yield()
            try await Task.sleep(for: .milliseconds(2))
        }
        Issue.record("timed out waiting for state transition")
    }
}
