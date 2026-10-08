//
//  NotebookScopedPullTests.swift
//  Books & Vocab Tests
//
//  #2102 — AddLink's local projection calls `pullCardsToLocal(notebookId:)`.
//  That pull used to read the GLOBAL incremental boundary as its `since`,
//  write it back afterwards, and — whenever the boundary was clear — run a
//  full-sync orphan cleanup against a single notebook's cards. Result: other
//  notebooks' server changes since the old boundary were skipped forever, and
//  in the full-sync state their cards were deleted locally.
//
//  A notebook-scoped pull is a projection, not a sync: it must never read or
//  write `incrementalBoundary` (nor the payload-version marker that gates the
//  next full re-sync), and it must merge with `isIncremental: true` so orphan
//  cleanup never runs. `KeyRecordingDefaults` turns "never reads" into an
//  observation rather than an inference from final values. It only bites
//  because `pullCardsToLocal(defaults:)` hands the same object to the scoped
//  path (which must leave it untouched); a scoped path that never received
//  it would leave `.standard` as the only place a regression could show.
//
//  Harness (`PagedVocabTransport`, `VocabPullHarness`, …) lives in
//  VocabPullPaginationTests.swift.
//

import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct NotebookScopedPullTests {

    private let boundaryKey = KGService.SyncKeys.incrementalBoundary
    private let payloadVersionKey = KGService.SyncKeys.payloadVersion
    private let previousBoundary = 1_700_000_000.0

    /// Notebook A holds a1, a2; notebook B holds b1…b3 — all synced.
    private func seedTwoNotebooks() throws -> ModelContainer {
        let container = try VocabPullHarness.makeContainer()
        try VocabPullHarness.seedSynced(container, word: "a1", cardId: "ca1", notebookId: "A")
        try VocabPullHarness.seedSynced(container, word: "a2", cardId: "ca2", notebookId: "A")
        for index in 1...3 {
            try VocabPullHarness.seedSynced(container, word: "b\(index)", cardId: "cb\(index)", notebookId: "B")
        }
        return container
    }

    /// The AddLink projection result: the source card plus the newly linked target.
    private func notebookAPage(nextCursor: String? = nil) -> VocabPullPage {
        VocabPullPage(
            cards: [
                vocabCardJSON(id: "ca1", content: "a1", notebookId: "A"),
                vocabCardJSON(id: "ca3", content: "a3", notebookId: "A"),
            ],
            nextCursor: nextCursor
        )
    }

    private func pullNotebookA(
        _ service: KGService, container: ModelContainer, defaults: UserDefaults
    ) async throws -> KGPullOutcome {
        try await service.pullCardsToLocal(
            container: container, progress: nil, notebookId: "A", reporter: nil, defaults: defaults
        )
    }

    // MARK: - Steady state (boundary set)

    @Test func scopedPull_withBoundary_neverTouchesTheGlobalCursor() async throws {
        let container = try seedTwoNotebooks()
        let defaults = KeyRecordingDefaults.make(boundary: previousBoundary, payloadVersionCurrent: true)
        let transport = PagedVocabTransport(pages: [notebookAPage()])
        let service = VocabPullHarness.makeService(transport: transport)

        let outcome = try await pullNotebookA(service, container: container, defaults: defaults)
        let touched = defaults.touchedKeys

        #expect(touched.isDisjoint(with: [boundaryKey, payloadVersionKey]),
                "a notebook-scoped pull read or wrote the global sync cursor: \(touched)")
        #expect(defaults.double(forKey: boundaryKey) == previousBoundary)
        let requests = transport.vocabRequests
        #expect(requests.count == 1)
        #expect(requests.allSatisfy { vocabQueryValue($0, "notebook_id") == "A" })
        #expect(requests.allSatisfy { vocabQueryValue($0, "since") == nil },
                "the global boundary must not become a notebook pull's `since`")
        #expect(try VocabPullHarness.words(in: container, notebookId: "B") == ["b1", "b2", "b3"])
        #expect(try VocabPullHarness.words(in: container, notebookId: "A") == ["a1", "a2", "a3"])
        #expect(outcome.inserted == 1)
        #expect(outcome.deleted == 0)
    }

    // MARK: - Full-sync state (boundary cleared)

    /// With no boundary the old code ran a full sync scoped to A: 2 server
    /// cards against 5 local passes the mass-deletion guard (ratio 0.4,
    /// diff 3), so a2 and every card of notebook B were reaped.
    @Test func scopedPull_withoutBoundary_neverRunsOrphanCleanup() async throws {
        let container = try seedTwoNotebooks()
        let defaults = KeyRecordingDefaults.make(boundary: nil, payloadVersionCurrent: true)
        let transport = PagedVocabTransport(pages: [notebookAPage()])
        let service = VocabPullHarness.makeService(transport: transport)

        let outcome = try await pullNotebookA(service, container: container, defaults: defaults)
        let touched = defaults.touchedKeys

        #expect(try VocabPullHarness.words(in: container, notebookId: "B") == ["b1", "b2", "b3"],
                "other notebooks were reaped as orphans of a notebook-scoped pull")
        #expect(try VocabPullHarness.words(in: container, notebookId: "A") == ["a1", "a2", "a3"])
        #expect(outcome.deleted == 0)
        #expect(touched.isDisjoint(with: [boundaryKey, payloadVersionKey]))
        #expect(defaults.object(forKey: boundaryKey) == nil,
                "a notebook-scoped pull must not establish the global boundary")
    }

    /// A pending payload-version upgrade belongs to the next GLOBAL pull. A
    /// scoped pull that cleared the boundary and then marked the version
    /// current would silently cancel that full re-sync for every notebook.
    @Test func scopedPull_leavesAPendingPayloadUpgradeToTheGlobalPull() async throws {
        let container = try seedTwoNotebooks()
        let defaults = KeyRecordingDefaults.make(boundary: previousBoundary, payloadVersionCurrent: false)
        let transport = PagedVocabTransport(pages: [notebookAPage()])
        let service = VocabPullHarness.makeService(transport: transport)

        _ = try await pullNotebookA(service, container: container, defaults: defaults)

        #expect(defaults.double(forKey: boundaryKey) == previousBoundary)
        #expect(defaults.object(forKey: payloadVersionKey) == nil)
        #expect(try VocabPullHarness.words(in: container, notebookId: "B") == ["b1", "b2", "b3"])
    }

    // MARK: - Pagination

    @Test func scopedPull_followsNextCursorWithinTheNotebook() async throws {
        let container = try seedTwoNotebooks()
        let defaults = KeyRecordingDefaults.make(boundary: previousBoundary, payloadVersionCurrent: true)
        let transport = PagedVocabTransport(pages: [
            notebookAPage(nextCursor: "cursor-page-2"),
            VocabPullPage(cards: [vocabCardJSON(id: "ca4", content: "a4", notebookId: "A")]),
        ])
        let service = VocabPullHarness.makeService(transport: transport)

        let outcome = try await pullNotebookA(service, container: container, defaults: defaults)

        let requests = transport.vocabRequests
        #expect(requests.map { vocabQueryValue($0, "cursor") } == [nil, "cursor-page-2"])
        #expect(requests.allSatisfy {
            vocabQueryValue($0, "notebook_id") == "A" && vocabQueryValue($0, "since") == nil
        })
        #expect(try VocabPullHarness.words(in: container, notebookId: "A") == ["a1", "a2", "a3", "a4"])
        #expect(outcome.inserted == 2)
        #expect(defaults.double(forKey: boundaryKey) == previousBoundary)
    }
}

/// `UserDefaults` that records every key the code under test reads or writes.
final class KeyRecordingDefaults: UserDefaults {
    private let lock = NSLock()
    private var touched: Set<String> = []

    /// Seeds the sync keys, then forgets the seeding so only the pull's own
    /// accesses are recorded.
    static func make(boundary: Double?, payloadVersionCurrent: Bool) -> KeyRecordingDefaults {
        let defaults = KeyRecordingDefaults(suiteName: "test.notebook-pull.\(UUID().uuidString)")!
        if let boundary {
            defaults.set(boundary, forKey: KGService.SyncKeys.incrementalBoundary)
        }
        if payloadVersionCurrent {
            defaults.set(KGService.SyncKeys.currentPayloadVersion, forKey: KGService.SyncKeys.payloadVersion)
        }
        defaults.lock.withLock { defaults.touched.removeAll() }
        return defaults
    }

    /// Keys accessed so far. Take it before asserting on stored values — those
    /// reads are recorded too.
    var touchedKeys: Set<String> { lock.withLock { touched } }

    private func note(_ key: String) {
        lock.withLock { _ = touched.insert(key) }
    }

    override func object(forKey defaultName: String) -> Any? {
        note(defaultName)
        return super.object(forKey: defaultName)
    }

    override func double(forKey defaultName: String) -> Double {
        note(defaultName)
        return super.double(forKey: defaultName)
    }

    override func integer(forKey defaultName: String) -> Int {
        note(defaultName)
        return super.integer(forKey: defaultName)
    }

    override func set(_ value: Any?, forKey defaultName: String) {
        note(defaultName)
        super.set(value, forKey: defaultName)
    }

    override func set(_ value: Double, forKey defaultName: String) {
        note(defaultName)
        super.set(value, forKey: defaultName)
    }

    override func set(_ value: Int, forKey defaultName: String) {
        note(defaultName)
        super.set(value, forKey: defaultName)
    }

    override func removeObject(forKey defaultName: String) {
        note(defaultName)
        super.removeObject(forKey: defaultName)
    }
}
