//
//  SharedDeckCopyControllerTests.swift
//  Books & Vocab Tests
//
//  Explore 複製 controller —— 四態轉移 + idempotencyKey 穩定性契約。
//  核心不變式：一個「複製意圖」及其所有 retry 共用同一把 key（server 冪等短路，
//  絕不併發不同-key 打出重複 notebook）；key 只在觀察到成功時清除，一個新複製才生新 key。
//

#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

@MainActor
struct SharedDeckCopyControllerTests {

    private func response(_ id: String = "nb1", already: Bool = false) -> DeckCopyResponse {
        DeckCopyResponse(
            notebookId: id, notebookName: "GRE 3000", deckId: "d1",
            sourceVersion: 2, cardCount: 42, alreadyCopied: already
        )
    }

    /// Scriptable `DeckCopying` fake: records every key it received, replays a
    /// per-call scripted outcome (last entry repeats).
    private final class FakeDeckCopier: DeckCopying {
        private(set) var receivedKeys: [String] = []
        private(set) var receivedNames: [String?] = []
        private var results: [Result<DeckCopyResponse, Error>]
        private var callCount = 0
        init(_ results: [Result<DeckCopyResponse, Error>]) { self.results = results }
        func copyDeck(deckId: String, idempotencyKey: String, notebookName: String?) async throws -> DeckCopyResponse {
            receivedKeys.append(idempotencyKey)
            receivedNames.append(notebookName)
            let r = results[min(callCount, results.count - 1)]
            callCount += 1
            return try r.get()
        }
    }

    private func controller() -> SharedDeckCopyController {
        var n = 0
        return SharedDeckCopyController(makeKey: { n += 1; return "key-\(n)" })
    }

    // MARK: - Success

    @Test func success_transitions_to_success_and_clears_key() async {
        let c = controller()
        let fake = FakeDeckCopier([.success(response(already: false))])
        await c.copy(deckId: "d1", notebookName: "GRE 3000", using: fake)

        #expect(c.state == .success(.init(notebookId: "nb1", notebookName: "GRE 3000", cardCount: 42, alreadyCopied: false)))
        #expect(fake.receivedKeys == ["key-1"])
        #expect(fake.receivedNames == ["GRE 3000"])
        #expect(c.currentIdempotencyKey == nil, "intent fulfilled → key cleared so a later copy is a new intent")
    }

    @Test func success_invokes_afterCopy_with_response() async {
        let c = controller()
        let fake = FakeDeckCopier([.success(response("nbX"))])
        var seen: DeckCopyResponse?
        await c.copy(deckId: "d1", notebookName: nil, using: fake) { resp in seen = resp }
        #expect(seen?.notebookId == "nbX")
    }

    // MARK: - Failure keeps the key for retry

    @Test func failure_transitions_and_retains_key() async {
        let c = controller()
        let fake = FakeDeckCopier([.failure(URLError(.timedOut))])
        await c.copy(deckId: "d1", notebookName: "GRE 3000", using: fake)

        if case .failure = c.state {} else { Issue.record("expected .failure, got \(c.state)") }
        #expect(c.currentIdempotencyKey == "key-1", "a failed attempt keeps its key so retry reuses it")
    }

    // MARK: - Retry reuses the SAME key (the core anti-duplicate invariant)

    @Test func retry_reuses_same_idempotency_key() async {
        let c = controller()
        // First call fails, second (retry) succeeds.
        let fake = FakeDeckCopier([.failure(URLError(.networkConnectionLost)), .success(response())])
        await c.copy(deckId: "d1", notebookName: "GRE 3000", using: fake)   // fails, key-1
        await c.copy(deckId: "d1", notebookName: "GRE 3000", using: fake)   // retry, MUST reuse key-1

        #expect(fake.receivedKeys == ["key-1", "key-1"], "retry must reuse the same key so the server short-circuits, never minting a duplicate")
        if case .success = c.state {} else { Issue.record("expected .success after retry, got \(c.state)") }
        #expect(c.currentIdempotencyKey == nil)
    }

    // MARK: - A fresh copy AFTER success is a NEW intent → new key

    @Test func copy_after_success_uses_fresh_key() async {
        let c = controller()
        let fake = FakeDeckCopier([.success(response())])
        await c.copy(deckId: "d1", notebookName: "GRE 3000", using: fake)   // key-1, success → cleared
        await c.copy(deckId: "d1", notebookName: "GRE 3000", using: fake)   // NEW intent → key-2

        #expect(fake.receivedKeys == ["key-1", "key-2"], "a new copy after success is a new intent and must mint a fresh key")
    }

    // MARK: - alreadyCopied surfaces on the outcome (idempotent replay recovery)

    @Test func alreadyCopied_response_surfaces_on_outcome() async {
        let c = controller()
        let fake = FakeDeckCopier([.success(response(already: true))])
        await c.copy(deckId: "d1", notebookName: nil, using: fake)
        if case .success(let outcome) = c.state {
            #expect(outcome.alreadyCopied == true)
        } else {
            Issue.record("expected .success, got \(c.state)")
        }
    }

}
#endif
