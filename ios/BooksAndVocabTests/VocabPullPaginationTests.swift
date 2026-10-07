//
//  VocabPullPaginationTests.swift
//  Books & Vocab Tests
//
//  #2101 — `GET /api/vocab` pages at 5,000 rows and hands the remainder out
//  through `X-Next-Cursor`. A pull that reads only the first page sees a
//  library that is missing its newest rows: a full sync then reaps those rows
//  as orphans, and the incremental boundary moves past rows that were never
//  fetched, so they never come back.
//
//  These drive the real `KGService` pull through a scripted transport and an
//  in-memory SwiftData store, so the assertions observe the request sequence,
//  the merged store, and the sync cursor exactly as production produces them.
//

import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct VocabPullPaginationTests {

    private let boundaryKey = KGService.SyncKeys.incrementalBoundary
    private let payloadVersionKey = KGService.SyncKeys.payloadVersion

    // MARK: - Full sync

    /// Two pages, local store holding cards from both. The cleanup must judge
    /// the *whole* server set, so page-2 cards survive, the page-2-only card
    /// lands, and the boundary is still unwritten when page 2 is requested.
    @Test func fullSync_followsNextCursor_andCleansUpOnlyAfterTheLastPage() async throws {
        let container = try VocabPullHarness.makeContainer()
        for index in 1...10 {
            try VocabPullHarness.seedSynced(container, word: "w\(index)", cardId: "c\(index)")
        }
        let defaults = VocabPullHarness.makeDefaults()
        let probe = BoundaryProbe(defaults: defaults)
        let transport = PagedVocabTransport(
            pages: [
                VocabPullPage(
                    cards: (1...6).map { vocabCardJSON(id: "c\($0)", content: "w\($0)") },
                    nextCursor: "cursor-page-2"
                ),
                VocabPullPage(cards: (7...11).map { vocabCardJSON(id: "c\($0)", content: "w\($0)") }),
            ],
            onVocabRequest: probe.observe
        )
        let service = VocabPullHarness.makeService(transport: transport)

        let outcome = try await service.pullCardsToLocal(
            container: container, progress: nil, notebookId: nil, reporter: nil, defaults: defaults
        )

        let requests = transport.vocabRequests
        #expect(requests.map { vocabQueryValue($0, "cursor") } == [nil, "cursor-page-2"],
                "the pull must follow X-Next-Cursor to page 2")
        #expect(requests.allSatisfy { vocabQueryValue($0, "since") == nil })
        #expect(try VocabPullHarness.words(in: container) == Set((1...11).map { "w\($0)" }),
                "page-2 cards were reaped as orphans or never merged")
        #expect(outcome.inserted == 1)
        #expect(outcome.deleted == 0)
        #expect(probe.boundaries == [nil, nil], "boundary written before the last page was read")
        #expect(defaults.double(forKey: boundaryKey) > 0)
    }

    /// A failing page 2 means the server set is unknown: nothing may be reaped
    /// and neither the boundary nor the payload-version marker may move.
    @Test func fullSync_failingSecondPage_abortsCleanupAndBoundary() async throws {
        let container = try VocabPullHarness.makeContainer()
        for index in 1...10 {
            try VocabPullHarness.seedSynced(container, word: "w\(index)", cardId: "c\(index)")
        }
        let defaults = VocabPullHarness.makeDefaults()
        let transport = PagedVocabTransport(pages: [
            VocabPullPage(
                cards: (1...6).map { vocabCardJSON(id: "c\($0)", content: "w\($0)") },
                nextCursor: "cursor-page-2"
            ),
            VocabPullPage(statusCode: 400),
        ])
        let service = VocabPullHarness.makeService(transport: transport)

        await #expect(throws: KGError.self) {
            try await service.pullCardsToLocal(
                container: container, progress: nil, notebookId: nil, reporter: nil, defaults: defaults
            )
        }

        #expect(transport.vocabRequests.count == 2)
        #expect(try VocabPullHarness.words(in: container) == Set((1...10).map { "w\($0)" }),
                "orphan cleanup ran on a partial read")
        #expect(defaults.object(forKey: boundaryKey) == nil, "boundary advanced past unread rows")
        #expect(defaults.object(forKey: payloadVersionKey) == nil,
                "payload upgrade marked done although the full re-sync never finished")
    }

    // MARK: - Incremental sync

    /// Every page re-sends the same `since` (the server binds the cursor to it)
    /// and the boundary only advances once the last page is in.
    @Test func incrementalSync_followsNextCursor_withStableSince() async throws {
        let container = try VocabPullHarness.makeContainer()
        try VocabPullHarness.seedSynced(container, word: "w1", cardId: "c1")
        try VocabPullHarness.seedSynced(container, word: "w2", cardId: "c2")
        let previousBoundary = 1_700_000_000.0
        let defaults = VocabPullHarness.makeDefaults(boundary: previousBoundary)
        let probe = BoundaryProbe(defaults: defaults)
        let transport = PagedVocabTransport(
            pages: [
                VocabPullPage(cards: [vocabCardJSON(id: "c1", content: "w1")], nextCursor: "cursor-page-2"),
                VocabPullPage(cards: [vocabCardJSON(id: "c3", content: "w3")]),
            ],
            onVocabRequest: probe.observe
        )
        let service = VocabPullHarness.makeService(transport: transport)

        let outcome = try await service.pullCardsToLocal(
            container: container, progress: nil, notebookId: nil, reporter: nil, defaults: defaults
        )

        let requests = transport.vocabRequests
        #expect(requests.map { vocabQueryValue($0, "cursor") } == [nil, "cursor-page-2"])
        let sinceValues = requests.map { vocabQueryValue($0, "since") }
        #expect(sinceValues.count == 2)
        #expect(sinceValues.allSatisfy { $0 != nil && $0 == sinceValues.first! },
                "the cursor is scoped to `since`; page 2 must repeat it verbatim")
        #expect(try VocabPullHarness.words(in: container) == ["w1", "w2", "w3"])
        #expect(outcome.inserted == 1)
        #expect(probe.boundaries == [previousBoundary, previousBoundary])
        #expect(defaults.double(forKey: boundaryKey) > previousBoundary)
    }

    @Test func incrementalSync_failingSecondPage_keepsTheBoundary() async throws {
        let container = try VocabPullHarness.makeContainer()
        try VocabPullHarness.seedSynced(container, word: "w1", cardId: "c1")
        let previousBoundary = 1_700_000_000.0
        let defaults = VocabPullHarness.makeDefaults(boundary: previousBoundary)
        let transport = PagedVocabTransport(pages: [
            VocabPullPage(cards: [vocabCardJSON(id: "c2", content: "w2")], nextCursor: "cursor-page-2"),
            VocabPullPage(statusCode: 400),
        ])
        let service = VocabPullHarness.makeService(transport: transport)

        await #expect(throws: KGError.self) {
            try await service.pullCardsToLocal(
                container: container, progress: nil, notebookId: nil, reporter: nil, defaults: defaults
            )
        }

        #expect(transport.vocabRequests.count == 2)
        #expect(defaults.double(forKey: boundaryKey) == previousBoundary,
                "boundary advanced although page 2 was never read")
    }

    /// A server that repeats a cursor would otherwise loop forever. It must
    /// fail like any other bad page — and commit nothing.
    @Test func repeatedCursor_failsInsteadOfLooping() async throws {
        let container = try VocabPullHarness.makeContainer()
        try VocabPullHarness.seedSynced(container, word: "w1", cardId: "c1")
        let defaults = VocabPullHarness.makeDefaults()
        let transport = PagedVocabTransport(pages: [
            VocabPullPage(cards: [vocabCardJSON(id: "c1", content: "w1")], nextCursor: "stuck"),
            VocabPullPage(cards: [vocabCardJSON(id: "c1", content: "w1")], nextCursor: "stuck"),
        ])
        let service = VocabPullHarness.makeService(transport: transport)

        await #expect(throws: KGError.self) {
            try await service.pullCardsToLocal(
                container: container, progress: nil, notebookId: nil, reporter: nil, defaults: defaults
            )
        }

        #expect(transport.vocabRequests.count == 2)
        #expect(defaults.object(forKey: boundaryKey) == nil)
    }

    // MARK: - Explore copy pull

    /// The post-copy notebook fetch reads the same paged endpoint; a copied
    /// notebook larger than one page must land whole.
    @Test func copiedDeckPull_followsNextCursor() async throws {
        let container = try VocabPullHarness.makeContainer()
        let transport = PagedVocabTransport(pages: [
            VocabPullPage(
                cards: [
                    vocabCardJSON(id: "cc1", content: "ephemeral", notebookId: "nb-copied"),
                    vocabCardJSON(id: "cc2", content: "serendipity", notebookId: "nb-copied"),
                ],
                nextCursor: "cursor-page-2"
            ),
            VocabPullPage(cards: [vocabCardJSON(id: "cc3", content: "petrichor", notebookId: "nb-copied")]),
        ])
        let service = VocabPullHarness.makeService(transport: transport)

        await service.pullCopiedDeck(container: container, notebookId: "nb-copied")

        let requests = transport.vocabRequests
        #expect(requests.map { vocabQueryValue($0, "cursor") } == [nil, "cursor-page-2"])
        #expect(requests.allSatisfy { vocabQueryValue($0, "notebook_id") == "nb-copied" })
        #expect(try VocabPullHarness.words(in: container, notebookId: "nb-copied")
                == ["ephemeral", "serendipity", "petrichor"])
    }
}

// MARK: - Shared pull harness (also used by NotebookScopedPullTests)

/// One scripted `GET /api/vocab` response.
struct VocabPullPage {
    var statusCode: Int = 200
    /// `KGCard` JSON objects, joined into the response array.
    var cards: [String] = []
    /// Sent as `X-Next-Cursor` when non-nil.
    var nextCursor: String?
}

/// Serves `/api/vocab` pages in script order and records each request; every
/// other path answers 404. `onVocabRequest` runs before the response is
/// returned, so a test can observe client state at the moment page N is asked
/// for. An unscripted `/api/vocab` request gets a non-retryable 418 so a
/// runaway loop fails fast instead of hanging.
final class PagedVocabTransport: KGHTTPTransport, @unchecked Sendable {
    private let lock = NSLock()
    private var pages: [VocabPullPage]
    private var recorded: [URLRequest] = []
    private let onVocabRequest: ((Int, URLRequest) -> Void)?

    init(pages: [VocabPullPage], onVocabRequest: ((Int, URLRequest) -> Void)? = nil) {
        self.pages = pages
        self.onVocabRequest = onVocabRequest
    }

    var vocabRequests: [URLRequest] { lock.withLock { recorded } }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        guard let url = request.url else { throw URLError(.badURL) }
        guard url.path.hasSuffix("/api/vocab") else {
            return Self.respond(url: url, statusCode: 404, body: #"{"detail":"not stubbed"}"#, cursor: nil)
        }
        let (index, page) = lock.withLock { () -> (Int, VocabPullPage?) in
            recorded.append(request)
            return (recorded.count - 1, pages.isEmpty ? nil : pages.removeFirst())
        }
        onVocabRequest?(index, request)
        guard let page else {
            return Self.respond(url: url, statusCode: 418, body: #"{"detail":"unscripted page"}"#, cursor: nil)
        }
        let body = page.statusCode == 200
            ? "[" + page.cards.joined(separator: ",") + "]"
            : #"{"detail":"scripted failure"}"#
        return Self.respond(url: url, statusCode: page.statusCode, body: body, cursor: page.nextCursor)
    }

    private static func respond(url: URL, statusCode: Int, body: String, cursor: String?) -> (Data, URLResponse) {
        var headers = ["Content-Type": "application/json", "X-Pipeline-Pending": "false"]
        if let cursor { headers["X-Next-Cursor"] = cursor }
        let response = HTTPURLResponse(url: url, statusCode: statusCode, httpVersion: nil, headerFields: headers)!
        return (Data(body.utf8), response)
    }
}

/// Records the incremental boundary as it stood when each `/api/vocab` page
/// was requested (`nil` = no boundary stored).
final class BoundaryProbe: @unchecked Sendable {
    private let lock = NSLock()
    private let defaults: UserDefaults
    private var observed: [Double?] = []

    init(defaults: UserDefaults) {
        self.defaults = defaults
    }

    var boundaries: [Double?] { lock.withLock { observed } }

    func observe(_ index: Int, _ request: URLRequest) {
        let boundary = defaults.object(forKey: KGService.SyncKeys.incrementalBoundary) as? Double
        lock.withLock { observed.append(boundary) }
    }
}

func vocabCardJSON(id: String, content: String, notebookId: String = "default") -> String {
    #"{"id":"\#(id)","content":"\#(content)","meaning":"m-\#(content)","examples":[],"mode":"recognition","isDeleted":false,"notebookId":"\#(notebookId)"}"#
}

func vocabQueryValue(_ request: URLRequest, _ name: String) -> String? {
    guard let url = request.url,
          let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
    else { return nil }
    return items.first { $0.name == name }?.value
}

@MainActor
enum VocabPullHarness {
    static func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            Book.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
        ])
        return try ModelContainer(
            for: schema,
            configurations: [ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)]
        )
    }

    static func makeService(transport: PagedVocabTransport) -> KGService {
        KGService(
            authSession: PullTestAuthSession(),
            sessionInvalidator: PullTestSessionInvalidator(),
            transport: transport,
            connectivityGate: FixedConnectivityGate(isConnected: true)
        )
    }

    /// Per-test defaults so the sync cursor never leaks between tests or into
    /// the host app's `.standard` domain. `boundary` set ⇒ the payload version
    /// is current too, which is the steady-state incremental configuration.
    static func makeDefaults(boundary: Double? = nil) -> UserDefaults {
        let defaults = UserDefaults(suiteName: "test.vocab-pull.\(UUID().uuidString)")!
        if let boundary {
            defaults.set(boundary, forKey: KGService.SyncKeys.incrementalBoundary)
            defaults.set(KGService.SyncKeys.currentPayloadVersion, forKey: KGService.SyncKeys.payloadVersion)
        }
        return defaults
    }

    static func seedSynced(
        _ container: ModelContainer, word: String, cardId: String, notebookId: String = "default"
    ) throws {
        let context = ModelContext(container)
        let entry = VocabularyEntry(word: word, translation: "seeded", context: "", bookTitle: "Seed Book")
        entry.notebookId = notebookId
        entry.kgCardId = cardId
        entry.markSynced()
        context.insert(entry)
        try context.save()
    }

    static func words(in container: ModelContainer, notebookId: String? = nil) throws -> Set<String> {
        let entries = try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
        return Set(entries.filter { notebookId == nil || $0.notebookId == notebookId }.map(\.word))
    }
}

@MainActor
final class PullTestAuthSession: AuthSessionProviding {
    let isLoggedIn = true
    /// Unsigned JWT whose `exp` is 2101-02-24 UTC, so the pre-request expiry check passes.
    let token: String? = "header.eyJleHAiOjQxMzg2Njg0MDB9.signature"
}

@MainActor
final class PullTestSessionInvalidator: SessionInvalidating {
    func logout(modelContainer: ModelContainer?, reason: String) {}
    func waitForPendingLocalDataCleanup() async {}
}
