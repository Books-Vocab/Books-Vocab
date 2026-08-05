import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("Dictionary phase 2A transport", .serialized)
struct DictionaryPhase2ATests {
    @Test("decodes backend search and entry wire shapes")
    func decodeBackendWire() throws {
        let search = try JSONDecoder().decode(DictionarySearchResponse.self, from: Data(Self.searchJSON.utf8))
        #expect(search.hits.first?.partsOfSpeech == ["adjective"])
        #expect(search.hits.first?.attribution.licenseName == "CC BY-SA 4.0")

        let detail = try JSONDecoder().decode(DictionaryEntryResponse.self, from: Data(Self.entryJSON.utf8))
        #expect(detail.entry.senses.first?.id == "sense_1")
        #expect(detail.entry.senses.first?.examples.first?.id == "example_1")
        #expect(detail.entry.pronunciations == ["/ˈluːsɪd/"])

        let projection = try JSONDecoder().decode(
            [KGDictionaryCardProjection].self,
            from: Data(Self.backendProjectionJSON.utf8)
        )
        #expect(projection.first?.card.id == "card-1")
        #expect(projection.first?.dictionaryEntry.entryKey == "en.bHVjaWQ")
        #expect(projection.first?.links.first?.toId == "card-2")

        let promotion = try JSONDecoder().decode(
            DictionaryPromotionResponse.self,
            from: Data(#"{"cardId":"card-1","cardRole":"dictionary","promotionState":"queued","alreadyPromoted":false}"#.utf8)
        )
        #expect(promotion.cardId == "card-1")
        #expect(promotion.promotionState == "queued")
    }

    @Test("materialize request uses backend field names")
    func encodeMaterializeRequest() throws {
        let request = DictionaryMaterializeLinkRequest(
            sourceCardId: "source", notebookId: "nb", provider: "free_dictionary",
            entryKey: "en.bHVjaWQ", senseKey: "sense_1", exampleKey: "example_1"
        )
        let object = try #require(try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: String])
        #expect(object["sourceCardId"] == "source")
        #expect(object["exampleKey"] == "example_1")
    }

    @Test("local candidates stay notebook-scoped and exclude self/already-linked")
    func localCandidates() {
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        let match = Self.entry("lucid", cardID: "target", notebook: "nb")
        let otherNotebook = Self.entry("lucidity", cardID: "other", notebook: "other")
        let linked = Self.entry("lucidly", cardID: "linked", notebook: "nb")
        source.graphLinksByKind = ["related": [
            KGCardLinkSummary(id: "link", cardId: "linked", word: "lucidly", kind: "related", label: "related", confidence: 1, reason: "")
        ]]

        let result = AddLinkCoordinator.localCandidates(
            query: "lucid", sourceEntry: source,
            allEntries: [source, match, otherNotebook, linked]
        )
        #expect(result.map(\.word) == ["lucid"])
    }

    @Test("reader visibility queues a durable edit and actor acknowledges only matching intent")
    func readerVisibilityOutbox() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let value = Self.entry("lucid", cardID: "card-1", notebook: "nb")
        value.markSynced()
        value.queueReaderVisibility(true)
        context.insert(value)
        try context.save()

        let actor = BackgroundSyncActor(modelContainer: container)
        let pending = try await actor.pendingReaderVisibilityEdits()
        #expect(pending.count == 1)
        #expect(pending.first?.cardID == "card-1")
        #expect(pending.first?.hidden == true)

        // The user changes their mind while the older `hidden=true` request is
        // in flight. Its late acknowledgement must not clear the newer false.
        value.queueReaderVisibility(false)
        try context.save()
        let retryActor = BackgroundSyncActor(modelContainer: container)
        try await retryActor.markReaderVisibilitySynced(cardID: "card-1", hidden: true)
        let stillPending = try await retryActor.pendingReaderVisibilityEdits()
        #expect(stillPending.count == 1)
        #expect(stillPending.first?.hidden == false)
        try await retryActor.markReaderVisibilitySynced(cardID: "card-1", hidden: false)
        let drained = try await retryActor.pendingReaderVisibilityEdits()
        #expect(drained.isEmpty)
    }

    @Test("reader visibility save rollback preserves an older pending intent")
    func readerVisibilitySaveRollback() {
        let value = Self.entry("lucid", cardID: "card-1", notebook: "nb")
        value.isExcludedFromReader = true
        value.readerVisibilitySyncPending = true

        value.queueReaderVisibility(false)
        value.restoreReaderVisibilityAfterSaveFailure(
            previousHidden: true,
            previousPending: true
        )

        #expect(value.isExcludedFromReader)
        #expect(value.readerVisibilitySyncPending)
    }

    @Test("reader visibility flush requests coalesce behind one owner") @MainActor
    func readerVisibilitySingleFlight() {
        let service = KGService()
        #expect(service.claimReaderVisibilityFlush())
        #expect(!service.claimReaderVisibilityFlush())
        #expect(service.finishReaderVisibilityFlushPass())
        #expect(!service.finishReaderVisibilityFlushPass())
    }

    @Test("reader visibility transport serializes rapid toggles and drains the latest intent") @MainActor
    func readerVisibilityTransportSerializesRapidToggles() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let value = Self.entry("lucid", cardID: "card-1", notebook: "nb")
        value.markSynced()
        value.queueReaderVisibility(true)
        context.insert(value)
        try context.save()

        ControlledDictionaryURLProtocol.reset(mode: .holdFirstVisibility)
        let service = Self.transportService()
        let migrationKey = "kg_dictionary_reader_visibility_migrated_v1"
        UserDefaults.standard.set(true, forKey: migrationKey)
        defer { UserDefaults.standard.removeObject(forKey: migrationKey) }

        let firstFlush = Task {
            try await service.flushReaderVisibilityOutbox(container: container)
        }
        try await ControlledDictionaryURLProtocol.waitForRequestCount(1)

        let toggleContext = ModelContext(container)
        let rows = try toggleContext.fetch(FetchDescriptor<VocabularyEntry>())
        let toggled = try #require(rows.first)
        toggled.queueReaderVisibility(false)
        try toggleContext.save()

        try await service.flushReaderVisibilityOutbox(container: container)
        ControlledDictionaryURLProtocol.releaseHeldVisibility()
        try await firstFlush.value

        let snapshot = ControlledDictionaryURLProtocol.snapshot()
        #expect(snapshot.visibilityValues == [true, false])
        #expect(snapshot.maximumConcurrency == 1)
        let pending = try await BackgroundSyncActor(modelContainer: container)
            .pendingReaderVisibilityEdits()
        #expect(pending.isEmpty)
    }

    @Test("legacy reader visibility 404 preserves the durable intent") @MainActor
    func readerVisibility404PreservesPending() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let value = Self.entry("lucid", cardID: "card-1", notebook: "nb")
        value.markSynced()
        value.queueReaderVisibility(true)
        context.insert(value)
        try context.save()

        ControlledDictionaryURLProtocol.reset(mode: .visibility404)
        let migrationKey = "kg_dictionary_reader_visibility_migrated_v1"
        UserDefaults.standard.set(true, forKey: migrationKey)
        defer { UserDefaults.standard.removeObject(forKey: migrationKey) }

        try await Self.transportService().flushReaderVisibilityOutbox(container: container)

        let pending = try await BackgroundSyncActor(modelContainer: container)
            .pendingReaderVisibilityEdits()
        #expect(pending.map(\.hidden) == [true])
    }

    @Test("promotion transport posts to the card promote endpoint") @MainActor
    func promotionTransportContract() async throws {
        ControlledDictionaryURLProtocol.reset(mode: .standard)

        let response = try await Self.transportService()
            .promoteDictionaryCard(cardId: "card-1")

        #expect(response.cardId == "card-1")
        #expect(response.promotionState == "queued")
        let snapshot = ControlledDictionaryURLProtocol.snapshot()
        #expect(snapshot.requests.last?.httpMethod == "POST")
        #expect(snapshot.requests.last?.url?.path == "/api/dictionary/cards/card-1/promote")
    }

    @Test("cancelled exact search cannot publish a stale response") @MainActor
    func cancelledSearchIsStaleSafe() async throws {
        let service = SlowDictionaryService()
        let coordinator = AddLinkCoordinator()
        coordinator.submitSearch(query: "old", using: service)
        coordinator.queryDidChange()
        try await Task.sleep(for: .milliseconds(80))
        #expect(coordinator.searchPhase == .idle)
        let searches = await service.searches
        #expect(searches == ["old"])
    }

    @Test("dictionary lookup starts only on explicit submit and resolves an entry") @MainActor
    func exactSearchSubmit() async throws {
        let service = ImmediateDictionaryService()
        let coordinator = AddLinkCoordinator()
        #expect(coordinator.searchPhase == .idle)
        let initialCount = await service.callCount
        #expect(initialCount == 0)

        coordinator.submitSearch(query: " lucid ", using: service)
        try await Task.sleep(for: .milliseconds(30))
        guard case .result(let entry, let cacheStatus) = coordinator.searchPhase else {
            Issue.record("expected a normalized dictionary result")
            return
        }
        #expect(entry.word == "lucid")
        #expect(cacheStatus == "fresh")
        let finalCount = await service.callCount
        #expect(finalCount == 2)
    }

    @Test("targeted dictionary merge preserves one row by card id")
    func targetedMergeByCardID() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let existing = Self.entry("lucid", cardID: "card-1", notebook: "nb")
        existing.cardRole = .learning
        existing.graphLinksByKind = ["related": [
            KGCardLinkSummary(id: "stale", cardId: "old", word: "old", kind: "related", label: "related", confidence: 1, reason: "")
        ]]
        existing.markSynced()
        context.insert(existing)
        try context.save()

        let projection = try JSONDecoder().decode(
            KGDictionaryCardProjection.self,
            from: Data(Self.projectionJSON.utf8)
        )
        let actor = BackgroundSyncActor(modelContainer: container)
        _ = try await actor.upsertDictionaryProjection(projection)

        let verificationContext = ModelContext(container)
        let rows = try verificationContext.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(rows.count == 1)
        #expect(rows.first?.id == existing.id)
        #expect(rows.first?.cardRole == .dictionary)
        #expect(rows.first?.dictionarySelectedExampleKey == "example_1")
        #expect(rows.first?.graphLinksByKind.isEmpty == true)
    }

    @Test("materialize retry reuses the same idempotency key and targeted-upserts") @MainActor
    func materializeRetry() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let source = Self.entry("source", cardID: "source", notebook: "nb")
        source.markSynced()
        context.insert(source)
        try context.save()

        let lexical = try JSONDecoder().decode(
            DictionaryEntryResponse.self, from: Data(Self.entryJSON.utf8)
        ).entry
        let service = RetryDictionaryService()
        let coordinator = AddLinkCoordinator()
        coordinator.select(senseKey: "sense_1", exampleKey: "example_1")

        await coordinator.materializeSelectedExample(
            sourceEntry: source, entry: lexical, using: service, container: container
        )
        #expect(coordinator.materializePhase == .failed)
        await coordinator.materializeSelectedExample(
            sourceEntry: source, entry: lexical, using: service, container: container
        )
        #expect(coordinator.materializePhase == .succeeded)
        let keys = await service.idempotencyKeys
        #expect(keys.count == 2)
        #expect(keys.first == keys.last)

        let verificationContext = ModelContext(container)
        let rows = try verificationContext.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(rows.filter { $0.kgCardId == "target" }.count == 1)
        #expect(source.graphLinksByKind.values.flatMap { $0 }.contains { $0.cardId == "target" })
    }

    private static func entry(_ word: String, cardID: String, notebook: String) -> VocabularyEntry {
        let value = VocabularyEntry(
            word: word, translation: word, context: "", bookTitle: "Book"
        )
        value.kgCardId = cardID
        value.notebookId = notebook
        return value
    }

    private static func container() throws -> ModelContainer {
        let schema = Schema([VocabularyEntry.self, ReviewRecord.self])
        let configuration = ModelConfiguration(
            isStoredInMemoryOnly: true,
            cloudKitDatabase: .none
        )
        return try ModelContainer(for: schema, configurations: [configuration])
    }

    @MainActor
    private static func transportService() -> KGService {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ControlledDictionaryURLProtocol.self]
        return KGService(
            authSession: DictionaryTestAuthSession(),
            sessionInvalidator: DictionaryTestSessionInvalidator(),
            urlSession: URLSession(configuration: configuration)
        )
    }

    fileprivate static let searchJSON = #"{"hits":[{"provider":"free_dictionary","dictionaryId":"wiktionary-en","entryKey":"en.bHVjaWQ","word":"lucid","language":"en","partsOfSpeech":["adjective"],"hasExamples":true,"attribution":{"provider":"free_dictionary","source_url":"https://en.wiktionary.org/wiki/lucid","license_name":"CC BY-SA 4.0","license_url":"https://creativecommons.org/licenses/by-sa/4.0/","attribution_text":"Wiktionary"}}],"cacheStatus":"fresh"}"#
    fileprivate static let entryJSON = #"{"entry":{"provider":"free_dictionary","dictionary_id":"wiktionary-en","schema_version":"1","entry_key":"en.bHVjaWQ","word":"lucid","language":"en","pronunciations":["/ˈluːsɪd/"],"forms":[],"senses":[{"key":"sense_1","part_of_speech":"adjective","definition":"clear","examples":[{"key":"example_1","text":"A lucid answer."}],"translations":[],"synonyms":[],"antonyms":[]}],"attribution":{"provider":"free_dictionary","source_url":"https://en.wiktionary.org/wiki/lucid","license_name":"CC BY-SA 4.0","license_url":"https://creativecommons.org/licenses/by-sa/4.0/","attribution_text":"Wiktionary"},"fetched_at":"2026-08-05T00:00:00Z","truncated":false},"cacheStatus":"fresh"}"#
    private static let backendProjectionJSON = #"[{"card":{"id":"card-1","content":"lucid","meaning":"clear","pos":"adjective","examples":["A lucid answer."],"inflections":[],"notebookId":"nb","cardRole":"dictionary","reviewEligible":false,"readerHidden":false,"promotionState":"idle","promotedAt":null,"isDeleted":false,"isArchived":false,"createdAt":"2026-08-05T00:00:00Z","updatedAt":"2026-08-05T00:00:00Z"},"dictionary":{"card":{"id":"card-1","content":"lucid","meaning":"clear","pos":"adjective","examples":["A lucid answer."],"inflections":[],"notebookId":"nb","cardRole":"dictionary","reviewEligible":false,"readerHidden":false,"promotionState":"idle","promotedAt":null,"isDeleted":false,"isArchived":false,"createdAt":"2026-08-05T00:00:00Z","updatedAt":"2026-08-05T00:00:00Z"},"entry":{"provider":"free_dictionary","dictionary_id":"wiktionary-en","schema_version":"1","entry_key":"en.bHVjaWQ","word":"lucid","language":"en","pronunciations":["/ˈluːsɪd/"],"forms":[],"senses":[{"key":"sense_1","part_of_speech":"adjective","definition":"clear","examples":[{"key":"example_1","text":"A lucid answer."}],"translations":[],"synonyms":[],"antonyms":[]}],"attribution":{"provider":"free_dictionary","source_url":"https://en.wiktionary.org/wiki/lucid","license_name":"CC BY-SA 4.0","license_url":"https://creativecommons.org/licenses/by-sa/4.0/","attribution_text":"Wiktionary"},"fetched_at":"2026-08-05T00:00:00Z","truncated":false},"selectedSenseKey":"sense_1","selectedExampleKey":"example_1","materializationStatus":"active"},"readerHidden":false,"links":[{"id":"link-1","fromId":"card-1","toId":"card-2","kind":"related","confidence":0.9,"reason":"related"}]}]"#
    private static let projectionJSON = #"{"card":{"id":"card-1","content":"lucid","meaning":"clear","pos":"adjective","examples":["A lucid answer."],"mode":"recognition","notebookId":"nb","cardRole":"dictionary","reviewEligible":false,"readerHidden":false,"promotionState":"idle"},"dictionaryEntry":{"provider":"free_dictionary","dictionary_id":"wiktionary-en","schema_version":"1","entry_key":"en.bHVjaWQ","word":"lucid","language":"en","pronunciations":["/ˈluːsɪd/"],"forms":[],"senses":[{"key":"sense_1","part_of_speech":"adjective","definition":"clear","examples":[{"key":"example_1","text":"A lucid answer."}],"translations":[],"synonyms":[],"antonyms":[]}],"attribution":{"provider":"free_dictionary","source_url":"https://en.wiktionary.org/wiki/lucid","license_name":"CC BY-SA 4.0","license_url":"https://creativecommons.org/licenses/by-sa/4.0/","attribution_text":"Wiktionary"},"fetched_at":"2026-08-05T00:00:00Z","truncated":false},"selectedSenseKey":"sense_1","selectedExampleKey":"example_1","materializationStatus":"active"}"#
}

@MainActor
private final class DictionaryTestAuthSession: AuthSessionProviding {
    let isLoggedIn = true
    let token: String? = "dictionary-test-token"
}

@MainActor
private final class DictionaryTestSessionInvalidator: SessionInvalidating {
    func logout(modelContainer: ModelContainer?, reason: String) {}
    func waitForPendingLocalDataCleanup() async {}
}

private final class ControlledDictionaryURLProtocol: URLProtocol, @unchecked Sendable {
    enum Mode { case standard, holdFirstVisibility, visibility404 }

    struct Snapshot {
        let requests: [URLRequest]
        let visibilityValues: [Bool]
        let maximumConcurrency: Int
    }

    private struct State {
        var mode: Mode = .standard
        var requests: [URLRequest] = []
        var visibilityValues: [Bool] = []
        var inFlight = 0
        var maximumConcurrency = 0
        var heldProtocol: ControlledDictionaryURLProtocol?
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var state = State()

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let request = request
        let body = request.httpBody
            ?? URLProtocol.property(
                forKey: KGService.requestBodyURLProtocolPropertyKey,
                in: request
            ) as? Data
        let readerHidden = body.flatMap {
            (try? JSONSerialization.jsonObject(with: $0) as? [String: Bool])?["readerHidden"]
        }
        let action: (hold: Bool, status: Int, body: Data) = Self.lock.withLock {
            Self.state.requests.append(request)
            Self.state.inFlight += 1
            Self.state.maximumConcurrency = max(Self.state.maximumConcurrency, Self.state.inFlight)
            if let readerHidden { Self.state.visibilityValues.append(readerHidden) }

            if Self.state.mode == .holdFirstVisibility,
               readerHidden == true,
               Self.state.heldProtocol == nil {
                Self.state.heldProtocol = self
                return (true, 200, Self.cardData(readerHidden: true))
            }
            if Self.state.mode == .visibility404, readerHidden != nil {
                return (false, 404, Data(#"{"detail":"not found"}"#.utf8))
            }
            if request.url?.path.hasSuffix("/promote") == true {
                return (false, 200, Data(#"{"cardId":"card-1","cardRole":"dictionary","promotionState":"queued","alreadyPromoted":false}"#.utf8))
            }
            return (false, 200, Self.cardData(readerHidden: readerHidden ?? false))
        }
        if !action.hold { respond(status: action.status, body: action.body) }
    }

    override func stopLoading() {}

    static func reset(mode: Mode) {
        lock.withLock { state = State(mode: mode) }
    }

    static func snapshot() -> Snapshot {
        lock.withLock {
            Snapshot(
                requests: state.requests,
                visibilityValues: state.visibilityValues,
                maximumConcurrency: state.maximumConcurrency
            )
        }
    }

    static func waitForRequestCount(_ count: Int) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(2))
        while snapshot().requests.count < count {
            guard clock.now < deadline else {
                throw KGError.serverError("Timed out waiting for controlled request")
            }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    static func releaseHeldVisibility() {
        let held = lock.withLock { () -> ControlledDictionaryURLProtocol? in
            defer { state.heldProtocol = nil }
            return state.heldProtocol
        }
        held?.respond(status: 200, body: cardData(readerHidden: true))
    }

    private func respond(status: Int, body: Data) {
        guard let url = request.url,
              let response = HTTPURLResponse(
                url: url, statusCode: status, httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
              ) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
        Self.lock.withLock { Self.state.inFlight -= 1 }
    }

    private static func cardData(readerHidden: Bool) -> Data {
        Data(#"{"id":"card-1","content":"lucid","meaning":"clear","examples":[],"mode":"recognition","notebookId":"nb","cardRole":"dictionary","reviewEligible":false,"readerHidden":\#(readerHidden),"promotionState":"idle"}"#.utf8)
    }
}

private actor SlowDictionaryService: DictionaryServing {
    private(set) var searches: [String] = []

    func searchDictionary(
        query: String, sourceLanguage: String, targetLanguage: String
    ) async throws -> DictionarySearchResponse {
        searches.append(query)
        try await Task.sleep(for: .milliseconds(50))
        return try JSONDecoder().decode(
            DictionarySearchResponse.self,
            from: Data(DictionaryPhase2ATests.searchJSON.utf8)
        )
    }
}

private actor RetryDictionaryService: DictionaryServing {
    private(set) var idempotencyKeys: [String] = []

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest, idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        idempotencyKeys.append(idempotencyKey)
        if idempotencyKeys.count == 1 { throw KGError.httpError(statusCode: 503, detail: "retry") }
        let json = #"{"targetCard":{"id":"target","content":"lucid","meaning":"clear","pos":"adjective","examples":["A lucid answer."],"inflections":[],"notebookId":"nb","cardRole":"dictionary","reviewEligible":false,"readerHidden":false,"promotionState":"idle","promotedAt":null,"isDeleted":false,"isArchived":false,"createdAt":"2026-08-05T00:00:00Z","updatedAt":"2026-08-05T00:00:00Z"},"link":{"id":"link-1","fromId":"source","toId":"target","kind":"related","confidence":0.9,"reason":"related"},"createdCard":true,"createdLink":true,"replayed":false}"#
        return try JSONDecoder().decode(DictionaryMaterializeLinkResponse.self, from: Data(json.utf8))
    }
}

private actor ImmediateDictionaryService: DictionaryServing {
    private(set) var callCount = 0

    func searchDictionary(
        query: String, sourceLanguage: String, targetLanguage: String
    ) async throws -> DictionarySearchResponse {
        callCount += 1
        #expect(query == "lucid")
        return try JSONDecoder().decode(
            DictionarySearchResponse.self,
            from: Data(DictionaryPhase2ATests.searchJSON.utf8)
        )
    }

    func fetchDictionaryEntry(
        provider: String, entryKey: String, targetLanguage: String
    ) async throws -> DictionaryEntryResponse {
        callCount += 1
        return try JSONDecoder().decode(
            DictionaryEntryResponse.self,
            from: Data(DictionaryPhase2ATests.entryJSON.utf8)
        )
    }
}
