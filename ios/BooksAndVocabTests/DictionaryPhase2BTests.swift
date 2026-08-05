import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("Dictionary phase 2B", .serialized)
struct DictionaryPhase2BTests {
    @Test("role filter keeps mixed ordering semantics")
    func roleFilterAndRecentSort() {
        let learning = Self.entry("zebra", role: .learning, date: Date(timeIntervalSince1970: 10))
        let dictionary = Self.entry("alpha", role: .dictionary, date: Date(timeIntervalSince1970: 20))
        let values = [learning, dictionary]

        #expect(VocabularyEntryPresentation.filterByRole(values, filter: .all).count == 2)
        #expect(VocabularyEntryPresentation.filterByRole(values, filter: .learning).map(\.word) == ["zebra"])
        #expect(VocabularyEntryPresentation.filterByRole(values, filter: .dictionary).map(\.word) == ["alpha"])
        #expect(VocabularyEntryPresentation.sortAndFilter(values, searchText: "", sortOption: .dateAdded, now: .now).map(\.word) == ["alpha", "zebra"])
        #expect(VocabularyEntryPresentation.sortAndFilter(values, searchText: "", sortOption: .default, now: .now).map(\.word) == ["zebra", "alpha"])
    }

    @Test("dictionary row is secondary book-badged and has no due state")
    func dictionaryRowStyle() {
        let value = Self.entry("lucid", role: .dictionary)
        value.difficultyTier = "advanced"
        value.nextReviewAt = .distantPast

        let row = value.wordRowViewData(
            showsReviewState: true,
            showsSourceContext: true,
            showsDifficultyTier: true,
            showsReviewProgress: true
        )

        #expect(row.wordTone == .secondary)
        #expect(row.leadingSystemImage == "book.closed")
        #expect(row.bookTitle == L10n.string("dictionary.cardSource"))
        #expect(row.statusText == nil)
        #expect(row.reviewProgress == nil)
        #expect(row.difficultyTier == nil)
    }

    @Test("offline detail exposes selected sense, other senses, forms, and provenance")
    func offlineDetailPresentation() throws {
        let value = Self.entry("lucid", role: .dictionary)
        value.dictionaryPayloadJSON = Self.lexicalJSON
        value.dictionaryProvider = "free_dictionary"
        value.dictionarySelectedSenseKey = "sense_2"
        value.dictionarySelectedExampleKey = "example_2"
        value.dictionarySourceURL = "https://en.wiktionary.org/wiki/lucid"
        value.dictionaryLicenseName = "CC BY-SA 4.0"
        value.dictionaryLicenseURL = "https://creativecommons.org/licenses/by-sa/4.0/"

        let detail = try #require(DictionaryDetailPresentation.make(from: value))
        #expect(detail.word == "lucid")
        #expect(detail.pronunciations == ["/ˈluːsɪd/"])
        #expect(detail.selectedSense.id == "sense_2")
        #expect(detail.selectedExample?.text == "A lucid explanation.")
        #expect(detail.otherSenses.map(\.id) == ["sense_1"])
        #expect(detail.translations == ["清楚的", "明晰的"])
        #expect(detail.forms == ["lucidly", "lucidity"])
        #expect(detail.provenance.provider == "free_dictionary")
        #expect(detail.provenance.licenseName == "CC BY-SA 4.0")

        let share = detail.shareText
        #expect(share.contains("free_dictionary"))
        #expect(share.contains("https://en.wiktionary.org/wiki/lucid"))
        #expect(share.contains("CC BY-SA 4.0"))
        #expect(!share.contains("word,translation"))
    }

    @Test("projection decodes promotion failure and merges promotion in place")
    func promotionProjectionMerge() async throws {
        let projection = try JSONDecoder().decode(
            KGDictionaryCardProjection.self,
            from: Data(Self.failedProjectionJSON.utf8)
        )
        #expect(projection.promotionErrorCode == "quota_exhausted")
        #expect(projection.promotionRetryable == true)

        let container = try Self.container()
        let context = ModelContext(container)
        let existing = Self.entry("lucid", role: .dictionary)
        existing.kgCardId = "card-1"
        existing.markSynced()
        context.insert(existing)
        try context.save()

        let originalID = existing.id
        _ = try await BackgroundSyncActor(modelContainer: container).upsertDictionaryProjection(projection)
        let rows = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        let merged = try #require(rows.first)
        #expect(rows.count == 1)
        #expect(merged.id == originalID)
        #expect(merged.promotionState == .failed)
        #expect(merged.promotionErrorCode == "quota_exhausted")
        #expect(merged.promotionRetryable)
        #expect(DictionaryPromotionFailure.classify(code: merged.promotionErrorCode) == .quotaExhausted)
    }

    @Test("promoted projection keeps dictionary payload on the same learning row")
    func promotedProjectionTransition() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let existing = Self.entry("lucid", role: .dictionary)
        existing.kgCardId = "card-1"
        existing.markSynced()
        context.insert(existing)
        try context.save()
        let originalID = existing.id

        let promoted = try JSONDecoder().decode(
            KGDictionaryCardProjection.self,
            from: Data(Self.promotedProjectionJSON.utf8)
        )
        _ = try await BackgroundSyncActor(modelContainer: container).upsertDictionaryProjection(promoted)

        let rows = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        let merged = try #require(rows.first)
        #expect(merged.id == originalID)
        #expect(merged.cardRole == .learning)
        #expect(merged.reviewEligible)
        #expect(merged.dictionaryPayloadJSON != nil)
        #expect(DictionaryDetailPresentation.make(from: merged) != nil)
    }

    @Test("dictionary graph node has a secondary tier and book badge")
    func graphNodeStyle() throws {
        let value = Self.entry("lucid", role: .dictionary)
        value.kgCardId = "card-1"
        value.markSynced()
        let links = [KGGraphLink(id: "link", fromId: "card-1", toId: "card-2", kind: "related", confidence: 1, reason: "")]

        let node = try #require(KnowledgeGraphPresentation.nodes(from: [value], links: links).first)
        #expect(node.tier == "dictionary")
        #expect(node.badgeSystemImage == "book.closed")
        #expect(node.ratio == nil)
    }

    @Test("dictionary lifecycle transport uses dedicated archive and delete contracts") @MainActor
    func lifecycleTransportContract() async throws {
        Phase2BURLProtocol.reset()
        let service = Self.transportService()

        let archived = try await service.archiveDictionaryCard(cardId: "card-1", archived: true, notebookId: "nb one")
        let unarchived = try await service.archiveDictionaryCard(cardId: "card-1", archived: false, notebookId: "nb one")
        let deleted = try await service.deleteDictionaryCard(cardId: "card-1", notebookId: "nb one")
        #expect(archived.isArchived == true)
        #expect(unarchived.isArchived == false)
        #expect(deleted.isDeleted == true)

        let requests = Phase2BURLProtocol.requests()
        #expect(requests.count == 3)
        #expect(requests[0].httpMethod == "PATCH")
        #expect(requests[0].url?.path == "/api/dictionary/cards/card-1/archive")
        let body = requests[0].httpBody ?? URLProtocol.property(
            forKey: KGService.requestBodyURLProtocolPropertyKey,
            in: requests[0]
        ) as? Data
        let object = try #require(body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })
        #expect(object["archived"] as? Bool == true)
        #expect(object["notebookId"] as? String == "nb one")
        #expect(requests[1].httpMethod == "PATCH")
        #expect(requests[2].httpMethod == "DELETE")
        #expect(requests[2].url?.path == "/api/dictionary/cards/card-1")
        #expect(URLComponents(url: try #require(requests[2].url), resolvingAgainstBaseURL: false)?.queryItems?.first?.value == "nb one")
    }

    @Test("sync delete routing keeps dictionary cards off legacy vocab endpoints")
    func deleteRoutingPartition() {
        let learning = Self.entry("learn", role: .learning)
        let dictionary = Self.entry("lookup", role: .dictionary)
        learning.queueDelete()
        dictionary.queueDelete()

        let partition = SyncCoordinator.partitionDeletesByRole([dictionary, learning])
        #expect(partition.learning.map(\.word) == ["learn"])
        #expect(partition.dictionary.map(\.word) == ["lookup"])
    }

    /// Reader / PDF「移除」→ `queueDelete()` → outbox。Outbox 的 drain 必須依
    /// `cardRole` 分流：字典卡走專用 delete（server 端 graph link rollback +
    /// archive refcount），走 legacy `batchDeleteCards` / `deleteCard` 會靜默
    /// 漏掉 rollback，本地 peer 上的 link summary 也會變成指向不存在的卡。
    @Test("dictionary delete drains through the dedicated endpoint and rolls back graph links") @MainActor
    func dictionaryDeleteDrainRoutingAndRollback() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let dictionary = Self.entry("lookup", role: .dictionary)
        dictionary.kgCardId = "card-1"
        dictionary.notebookId = "nb one"
        let peer = Self.entry("peer", role: .learning)
        peer.kgCardId = "card-2"
        peer.notebookId = "nb one"
        peer.graphLinksByKind = ["related": [Self.linkSummary(to: "card-1")]]
        context.insert(dictionary)
        context.insert(peer)
        try context.save()
        dictionary.queueDelete()
        try context.save()

        var calls: [(cardID: String, notebookID: String)] = []
        let outcome = await SyncCoordinator.drainDictionaryDeletes(
            [dictionary],
            peers: [peer],
            modelContext: context
        ) { cardID, notebookID in
            calls.append((cardID, notebookID))
            return try JSONDecoder().decode(KGCard.self, from: Data(Self.deletedCardJSON.utf8))
        }

        #expect(outcome.deleted == 1)
        #expect(outcome.failedWords.isEmpty)
        #expect(calls.map(\.cardID) == ["card-1"])
        #expect(calls.map(\.notebookID) == ["nb one"])
        #expect(peer.graphLinksByKind["related"] == nil)
        try context.save()
        let survivors = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(survivors.map(\.word) == ["peer"])
    }

    /// 失敗必須是 no-op：本地 entry 與 peer 的 link 都要留著等下輪重試，
    /// 否則一次網路錯誤就把 link 從本地抹掉、server 卻還留著。
    @Test("failed dictionary delete keeps the row and its graph links") @MainActor
    func dictionaryDeleteFailureIsNonDestructive() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let dictionary = Self.entry("lookup", role: .dictionary)
        dictionary.kgCardId = "card-1"
        let peer = Self.entry("peer", role: .learning)
        peer.kgCardId = "card-2"
        peer.graphLinksByKind = ["related": [Self.linkSummary(to: "card-1")]]
        context.insert(dictionary)
        context.insert(peer)
        try context.save()
        dictionary.queueDelete()

        let outcome = await SyncCoordinator.drainDictionaryDeletes(
            [dictionary],
            peers: [peer],
            modelContext: context
        ) { _, _ in throw KGError.serverError("boom") }

        #expect(outcome.deleted == 0)
        #expect(outcome.failedWords == ["lookup"])
        #expect(dictionary.isFailed)
        #expect(peer.graphLinksByKind["related"]?.count == 1)
        try context.save()
        let survivors = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        #expect(Set(survivors.map(\.word)) == ["lookup", "peer"])
    }

    /// `readerHidden` 是獨立維度，且本地 outbox 意圖優先於 server projection。
    /// Projection 套用時若無條件寫回 server 值，使用者剛在 reader 按下的隱藏
    /// 會被一份較舊的 projection 靜默回捲，而 outbox 也就沒東西可重試了。
    @Test("projection never overwrites an unflushed reader visibility intent") @MainActor
    func projectionDefersToPendingReaderVisibility() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let entry = Self.entry("lucid", role: .dictionary)
        entry.kgCardId = "card-1"
        entry.dictionaryPayloadJSON = Self.lexicalJSON
        entry.dictionarySelectedSenseKey = "sense_1"
        entry.dictionarySelectedExampleKey = "example_1"
        context.insert(entry)
        try context.save()

        // 使用者在 reader 隱藏了這張卡，outbox 尚未 flush。
        entry.queueReaderVisibility(true)
        try context.save()

        let lexical = try JSONDecoder().decode(LexicalEntry.self, from: Data(Self.lexicalJSON.utf8))
        let sense = try #require(lexical.senses.first { $0.id == "sense_2" })
        let scene = WordDetailSceneState()
        scene.selectDictionary(
            sense: sense, example: sense.examples.first,
            for: entry, allEntries: [entry],
            kgService: Phase2BSelectionService(), modelContext: context
        )
        await scene.waitForSelectionForTesting()

        // 正控：projection 真的套用了（否則下面三條斷言是空的）。
        #expect(entry.dictionarySelectedSenseKey == "sense_2")
        // server 那份帶的是舊的 readerHidden=false，不得覆寫本地意圖。
        #expect(entry.isExcludedFromReader)
        #expect(entry.readerVisibilitySyncPending)
        let pending = try await BackgroundSyncActor(modelContainer: container)
            .pendingReaderVisibilityEdits()
        #expect(pending.map(\.cardID) == ["card-1"])
        #expect(pending.first?.hidden == true)
    }

    /// Polling 必須有界。超過預算而 server 仍未收斂時要落到具名的
    /// timeout 失敗態並開放 Retry，不可讓使用者卡在永遠轉的 spinner。
    @Test("promotion polling is bounded and surfaces a retryable timeout") @MainActor
    func promotionPollingTimesOut() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let entry = Self.entry("lucid", role: .dictionary)
        entry.kgCardId = "card-1"
        context.insert(entry)
        try context.save()
        let service = Phase2BPromotionService(projections: [Self.projection(state: "running")])
        let scene = WordDetailSceneState()

        scene.promoteDictionary(
            entry,
            allEntries: [entry],
            kgService: service,
            modelContext: context,
            pollDelays: [.milliseconds(1)],
            maxPollAttempts: 3
        )
        await scene.waitForPromotionForTesting()

        #expect(await service.fetchCount == 3)
        #expect(entry.cardRole == .dictionary)
        #expect(entry.promotionState == .failed)
        #expect(entry.promotionErrorCode == DictionaryPromotionFailure.timeoutErrorCode)
        #expect(entry.promotionRetryable)
        #expect(DictionaryPromotionFailure.classify(code: entry.promotionErrorCode) == .timedOut)
    }

    /// 取代已移除的 Add Link 字典 catalog scenario：同一組非 happy-path 狀態
    /// 改由 coordinator 層的 unit test 釘住。
    @Test("dictionary search publishes loading, empty and rate-limited phases") @MainActor
    func searchPhaseTransitions() async throws {
        let empty = AddLinkCoordinator()
        empty.submitSearch(query: "lucid", using: Phase2BSearchService(outcome: .empty))
        #expect(empty.searchPhase == .loading)
        try await Self.settle { empty.searchPhase == .empty }
        #expect(empty.searchPhase == .empty)

        let limited = AddLinkCoordinator()
        limited.submitSearch(query: "lucid", using: Phase2BSearchService(outcome: .rateLimited))
        try await Self.settle { limited.searchPhase == .failed(.rateLimited) }
        #expect(limited.searchPhase == .failed(.rateLimited))

        let blank = AddLinkCoordinator()
        blank.submitSearch(query: "   ", using: Phase2BSearchService(outcome: .empty))
        #expect(blank.searchPhase == .idle)
    }

    @Test("slow promotion keeps polling until the same row becomes learning") @MainActor
    func slowPromotionPolling() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let entry = Self.entry("lucid", role: .dictionary)
        entry.kgCardId = "card-1"
        context.insert(entry)
        try context.save()
        let originalID = entry.id
        let service = Phase2BPromotionService(
            projections: [
                Self.projection(state: "queued"),
                Self.projection(state: "running"),
                Self.projection(state: "running"),
                Self.projection(state: "idle", role: "learning", reviewEligible: true),
            ]
        )
        let scene = WordDetailSceneState()

        scene.promoteDictionary(
            entry,
            allEntries: [entry],
            kgService: service,
            modelContext: context,
            pollDelays: [.milliseconds(1)]
        )
        await scene.waitForPromotionForTesting()

        #expect(entry.id == originalID)
        #expect(entry.cardRole == .learning)
        #expect(entry.reviewEligible)
        #expect(await service.fetchCount == 4)
    }

    @Test("rapid selection is last-intent-wins and preserves pending reader visibility") @MainActor
    func rapidSelectionLastIntentWins() async throws {
        let container = try Self.container()
        let context = ModelContext(container)
        let entry = Self.entry("lucid", role: .dictionary)
        entry.kgCardId = "card-1"
        entry.dictionaryPayloadJSON = Self.lexicalJSON
        entry.dictionarySelectedSenseKey = "sense_1"
        entry.dictionarySelectedExampleKey = "example_1"
        entry.isExcludedFromReader = true
        entry.readerVisibilitySyncPending = true
        context.insert(entry)
        try context.save()
        let lexical = try JSONDecoder().decode(LexicalEntry.self, from: Data(Self.lexicalJSON.utf8))
        let first = try #require(lexical.senses.first { $0.id == "sense_1" })
        let second = try #require(lexical.senses.first { $0.id == "sense_2" })
        let service = Phase2BSelectionService()
        let scene = WordDetailSceneState()

        scene.selectDictionary(
            sense: first, example: first.examples.first,
            for: entry, allEntries: [entry], kgService: service, modelContext: context
        )
        scene.selectDictionary(
            sense: second, example: second.examples.first,
            for: entry, allEntries: [entry], kgService: service, modelContext: context
        )
        await scene.waitForSelectionForTesting()
        try await Task.sleep(for: .milliseconds(60))

        #expect(entry.dictionarySelectedSenseKey == "sense_2")
        #expect(entry.dictionarySelectedExampleKey == "example_2")
        #expect(entry.isExcludedFromReader)
        #expect(entry.readerVisibilitySyncPending)
    }

    private static func entry(
        _ word: String,
        role: VocabularyCardRole,
        date: Date = Date(timeIntervalSince1970: 100)
    ) -> VocabularyEntry {
        let value = VocabularyEntry(
            word: word,
            translation: "clear",
            context: "A clear answer.",
            partOfSpeech: "adjective",
            bookTitle: "Book"
        )
        value.cardRole = role
        value.reviewEligible = role == .learning
        value.dateAdded = date
        value.markSynced()
        return value
    }

    private static func linkSummary(to cardID: String) -> KGCardLinkSummary {
        KGCardLinkSummary(
            id: "link-\(cardID)", cardId: cardID, word: "lookup",
            kind: "related", label: "related", confidence: 1, reason: ""
        )
    }

    /// Polls `condition` on the main actor instead of sleeping a fixed budget —
    /// a fixed sleep is either flaky or slow depending on machine load.
    private static func settle(
        timeout: Duration = .milliseconds(500),
        _ condition: @escaping @Sendable @MainActor () -> Bool
    ) async throws {
        let deadline = ContinuousClock.now.advanced(by: timeout)
        while ContinuousClock.now < deadline {
            if await MainActor.run(body: condition) { return }
            try await Task.sleep(for: .milliseconds(5))
        }
    }

    private static func container() throws -> ModelContainer {
        let schema = Schema([VocabularyEntry.self, Notebook.self])
        let configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: schema, configurations: [configuration])
    }

    @MainActor
    private static func transportService() -> KGService {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [Phase2BURLProtocol.self]
        return KGService(
            authSession: Phase2BAuthSession(),
            sessionInvalidator: Phase2BSessionInvalidator(),
            urlSession: URLSession(configuration: configuration)
        )
    }

    fileprivate static let deletedCardJSON = #"{"id":"card-1","content":"lookup","meaning":"clear","examples":[],"notebookId":"nb one","cardRole":"dictionary","reviewEligible":false,"readerHidden":false,"promotionState":"idle","isDeleted":true,"isArchived":false,"createdAt":"2026-08-05T00:00:00Z","updatedAt":"2026-08-05T00:00:00Z"}"#
    private static let lexicalJSON = #"{"provider":"free_dictionary","dictionaryId":"wiktionary-en","entryKey":"en.bHVjaWQ","schemaVersion":"1","word":"lucid","sourceLanguage":"en","targetLanguage":"zh-Hant","pronunciations":["/ˈluːsɪd/"],"senses":[{"id":"sense_1","partOfSpeech":"adjective","definition":"bright","translations":["明亮的"],"examples":[{"id":"example_1","text":"Lucid water."}],"synonyms":[],"antonyms":[]},{"id":"sense_2","partOfSpeech":"adjective","definition":"clear and easy to understand","translations":["清楚的","明晰的"],"examples":[{"id":"example_2","text":"A lucid explanation."}],"synonyms":["clear"],"antonyms":["confusing"]}],"forms":["lucidly","lucidity"],"sourceUrl":"https://en.wiktionary.org/wiki/lucid","licenseName":"CC BY-SA 4.0","licenseUrl":"https://creativecommons.org/licenses/by-sa/4.0/","attributionText":"Wiktionary contributors","fetchedAt":"2026-08-05T00:00:00Z","truncated":false}"#
    fileprivate static let failedProjectionJSON = #"{"card":{"id":"card-1","content":"lucid","meaning":"clear","pos":"adjective","examples":["A lucid explanation."],"notebookId":"default","cardRole":"dictionary","reviewEligible":false,"readerHidden":false,"promotionState":"failed","isDeleted":false,"isArchived":false},"entry":\#(lexicalJSON),"selectedSenseKey":"sense_2","selectedExampleKey":"example_2","materializationStatus":"active","promotionErrorCode":"quota_exhausted","promotionRetryable":true}"#
    private static let promotedProjectionJSON = failedProjectionJSON
        .replacingOccurrences(of: #""cardRole":"dictionary""#, with: #""cardRole":"learning""#)
        .replacingOccurrences(of: #""reviewEligible":false"#, with: #""reviewEligible":true"#)
        .replacingOccurrences(of: #""promotionState":"failed""#, with: #""promotionState":"idle""#)
        .replacingOccurrences(of: #","promotionErrorCode":"quota_exhausted","promotionRetryable":true"#, with: "")

    fileprivate static func projection(
        state: String = "idle",
        role: String = "dictionary",
        reviewEligible: Bool = false,
        senseKey: String = "sense_2",
        exampleKey: String = "example_2"
    ) -> KGDictionaryCardProjection {
        let value = failedProjectionJSON
            .replacingOccurrences(of: #""promotionState":"failed""#, with: #""promotionState":"\#(state)""#)
            .replacingOccurrences(of: #""cardRole":"dictionary""#, with: #""cardRole":"\#(role)""#)
            .replacingOccurrences(of: #""reviewEligible":false"#, with: #""reviewEligible":\#(reviewEligible)"#)
            .replacingOccurrences(of: #""selectedSenseKey":"sense_2""#, with: #""selectedSenseKey":"\#(senseKey)""#)
            .replacingOccurrences(of: #""selectedExampleKey":"example_2""#, with: #""selectedExampleKey":"\#(exampleKey)""#)
            .replacingOccurrences(of: #","promotionErrorCode":"quota_exhausted","promotionRetryable":true"#, with: "")
        return try! JSONDecoder().decode(KGDictionaryCardProjection.self, from: Data(value.utf8))
    }
}

private actor Phase2BPromotionService: DictionaryServing {
    private let projections: [KGDictionaryCardProjection]
    private(set) var fetchCount = 0

    init(projections: [KGDictionaryCardProjection]) {
        self.projections = projections
    }

    func promoteDictionaryCard(cardId: String) async throws -> DictionaryPromotionResponse {
        try JSONDecoder().decode(
            DictionaryPromotionResponse.self,
            from: Data(#"{"cardId":"card-1","cardRole":"dictionary","promotionState":"queued","alreadyPromoted":false}"#.utf8)
        )
    }

    func fetchDictionaryCard(cardId: String) async throws -> KGDictionaryCardProjection {
        let index = min(fetchCount, projections.count - 1)
        fetchCount += 1
        return projections[index]
    }
}

private final class Phase2BSearchService: DictionaryServing, @unchecked Sendable {
    enum Outcome {
        case empty
        case rateLimited
    }

    private let outcome: Outcome

    init(outcome: Outcome) { self.outcome = outcome }

    func searchDictionary(
        query: String, sourceLanguage: String, targetLanguage: String
    ) async throws -> DictionarySearchResponse {
        switch outcome {
        case .empty:
            return DictionarySearchResponse(hits: [], cacheStatus: "fresh")
        case .rateLimited:
            throw KGError.httpError(statusCode: 429, detail: "rate limited")
        }
    }
}

private actor Phase2BSelectionService: DictionaryServing {
    func updateDictionarySelection(
        cardId: String, senseKey: String, exampleKey: String
    ) async throws -> KGDictionaryCardProjection {
        let delay: Duration = senseKey == "sense_1" ? .milliseconds(45) : .milliseconds(2)
        let worker = Task {
            try? await Task.sleep(for: delay)
            return DictionaryPhase2BTests.projection(
                senseKey: senseKey,
                exampleKey: exampleKey
            )
        }
        return await worker.value
    }
}

@MainActor
private final class Phase2BAuthSession: AuthSessionProviding {
    let isLoggedIn = true
    let token: String? = "phase2b-token"
}

@MainActor
private final class Phase2BSessionInvalidator: SessionInvalidating {
    func logout(modelContainer: ModelContainer?, reason: String) {}
    func waitForPendingLocalDataCleanup() async {}
}

private final class Phase2BURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var captured: [URLRequest] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.withLock { Self.captured.append(request) }
        guard let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"]) else { return }
        let deleted = request.httpMethod == "DELETE"
        let requestBody = request.httpBody ?? URLProtocol.property(
            forKey: KGService.requestBodyURLProtocolPropertyKey,
            in: request
        ) as? Data
        let archived = requestBody.flatMap {
            (try? JSONSerialization.jsonObject(with: $0) as? [String: Any])?["archived"] as? Bool
        } ?? false
        let body = Data(#"{"id":"card-1","content":"lucid","meaning":"clear","examples":[],"notebookId":"nb one","cardRole":"dictionary","reviewEligible":false,"readerHidden":false,"promotionState":"idle","isDeleted":\#(deleted),"isArchived":\#(archived),"createdAt":"2026-08-05T00:00:00Z","updatedAt":"2026-08-05T00:00:00Z"}"#.utf8)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    static func reset() { lock.withLock { captured = [] } }
    static func requests() -> [URLRequest] { lock.withLock { captured } }
}
