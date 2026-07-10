//
//  SharedDeckCatalogServiceTests.swift
//  Books & Vocab Tests
//
//  Explore 目錄 reconcile 契約 —— empty-response mass-delete guard + tombstone/resurrect
//  + upsert 冪等。對標 PodcastSyncService reconcile 守衛（空 200 不整片刪本地 catalog）。
//

#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct SharedDeckCatalogServiceTests {

    // 回傳 container（非 context）：mainContext 由 container 擁有，若只回 context 而
    // 讓 container 出 scope 被釋放，context 會 dangling → 使用時 crash。呼叫端須把
    // container 綁在測試 scope 存活，再取其 mainContext。
    private func makeContainer() throws -> ModelContainer {
        try ModelContainer(
            for: SharedDeck.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
    }

    private func summary(_ id: String, title: String = "T") -> SharedDeckSummary {
        SharedDeckSummary(deckId: id, title: title, isOfficial: true, cardCount: 10)
    }

    private func decks(_ ctx: ModelContext) throws -> [SharedDeck] {
        try ctx.fetch(FetchDescriptor<SharedDeck>())
    }

    // MARK: - Upsert

    @Test func upsert_inserts_new_deck() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1", title: "GRE"), sortOrder: 0, context: ctx)
        try ctx.save()
        let all = try decks(ctx)
        #expect(all.count == 1)
        #expect(all.first?.remoteId == "d1")
        #expect(all.first?.title == "GRE")
        #expect(all.first?.isOfficial == true)
        #expect(all.first?.sortOrder == 0)
    }

    @Test func upsert_is_idempotent_by_remoteId() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1", title: "Old"), sortOrder: 0, context: ctx)
        SharedDeckCatalogService.upsertDeck(summary: summary("d1", title: "New"), sortOrder: 3, context: ctx)
        try ctx.save()
        let all = try decks(ctx)
        #expect(all.count == 1)                     // 同 remoteId → in-place update，不重複插入
        #expect(all.first?.title == "New")
        #expect(all.first?.sortOrder == 3)
    }

    @Test func upsert_parses_updatedAt_iso8601() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let s = SharedDeckSummary(deckId: "d1", title: "T", updatedAt: "2026-07-01T00:00:00Z")
        SharedDeckCatalogService.upsertDeck(summary: s, sortOrder: 0, context: ctx)
        try ctx.save()
        #expect(try decks(ctx).first?.updatedAt != nil)
    }

    // MARK: - Reconcile: empty-guard

    @Test func reconcile_empty_server_list_does_not_tombstone() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1"), sortOrder: 0, context: ctx)
        SharedDeckCatalogService.upsertDeck(summary: summary("d2"), sortOrder: 1, context: ctx)
        try ctx.save()

        // 空 200（短暫 hiccup）→ 絕不整片 tombstone。
        SharedDeckCatalogService.reconcileLocalState(serverSummaries: [], context: ctx)
        try ctx.save()

        let live = try decks(ctx).filter { !$0.isSoftDeleted }
        #expect(live.count == 2, "empty server list must not mass-delete the local catalog")
    }

    // MARK: - Reconcile: tombstone / resurrect

    @Test func reconcile_tombstones_deck_missing_from_server() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1"), sortOrder: 0, context: ctx)
        SharedDeckCatalogService.upsertDeck(summary: summary("d2"), sortOrder: 1, context: ctx)
        try ctx.save()

        // 伺服器只回 d1 → d2 被 tombstone。
        SharedDeckCatalogService.reconcileLocalState(serverSummaries: [summary("d1")], context: ctx)
        try ctx.save()

        let byId = Dictionary(uniqueKeysWithValues: try decks(ctx).map { ($0.remoteId, $0) })
        #expect(byId["d1"]?.isSoftDeleted == false)
        #expect(byId["d2"]?.isSoftDeleted == true)
    }

    @Test func reconcile_resurrects_tombstoned_deck_back_on_server() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1"), sortOrder: 0, context: ctx)
        try ctx.save()
        // 先 tombstone d1（伺服器回別的 deck）。
        SharedDeckCatalogService.reconcileLocalState(serverSummaries: [summary("other")], context: ctx)
        try ctx.save()
        #expect(try decks(ctx).first { $0.remoteId == "d1" }?.isSoftDeleted == true)

        // d1 重新出現 → 復活。
        SharedDeckCatalogService.reconcileLocalState(serverSummaries: [summary("d1")], context: ctx)
        try ctx.save()
        #expect(try decks(ctx).first { $0.remoteId == "d1" }?.isSoftDeleted == false)
    }

    @Test func upsert_resurrects_tombstoned_deck() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1"), sortOrder: 0, context: ctx)
        try ctx.save()
        SharedDeckCatalogService.reconcileLocalState(serverSummaries: [summary("other")], context: ctx)
        try ctx.save()
        // 直接 upsert d1 也應清 tombstone。
        SharedDeckCatalogService.upsertDeck(summary: summary("d1"), sortOrder: 0, context: ctx)
        try ctx.save()
        #expect(try decks(ctx).first { $0.remoteId == "d1" }?.isSoftDeleted == false)
    }

    // MARK: - Query building

    @Test func listURL_encodes_filters() {
        let q = SharedDeckCatalogService.BrowseQuery(
            text: "gre", category: "exam", languagePair: "en-zh", official: true, sort: "recency"
        )
        let url = SharedDeckCatalogService.listURL(query: q)
        #expect(url.contains("q=gre"))
        #expect(url.contains("category=exam"))
        #expect(url.contains("languagePair=en-zh"))
        #expect(url.contains("official=true"))
        #expect(url.contains("sort=recency"))
    }

    @Test func listURL_empty_query_has_no_query_string() {
        let url = SharedDeckCatalogService.listURL(query: SharedDeckCatalogService.BrowseQuery())
        #expect(!url.contains("?"))
        #expect(url.hasSuffix("/api/decks"))
    }

    // MARK: - Pagination (keyset cursor)
    //
    // `syncAll` must page the ENTIRE catalog before reconcile. Reconcile
    // tombstones any local deck absent from the server set, so feeding it a
    // single page (the pre-Phase-2b bug) mass-deletes every deck past page 1.

    private func listPage(_ ids: Range<Int>, nextCursor: String?) -> SharedDeckListResponse {
        SharedDeckListResponse(decks: ids.map { summary("d\($0)") }, nextCursor: nextCursor)
    }

    @Test func collectAllPages_follows_cursor_and_accumulates_every_page() async throws {
        let page0 = listPage(0..<20, nextCursor: "c1")   // full first page → more to come
        let page1 = listPage(20..<25, nextCursor: nil)   // deck "d24" lives ONLY here
        var seenCursors: [String?] = []
        let collected = try await SharedDeckCatalogService.collectAllPages { cursor in
            seenCursors.append(cursor)
            switch cursor {
            case .none: return page0
            case .some("c1"): return page1
            default: throw URLError(.badServerResponse)
            }
        }
        #expect(collected.summaries.count == 25)                    // union of both pages
        #expect(collected.summaries.contains { $0.deckId == "d24" }) // second-page deck present
        #expect(collected.truncated == false)                       // drained via nil cursor → authoritative
        #expect(seenCursors == [nil, "c1"])                         // followed nextCursor
        let ids = collected.summaries.map(\.deckId)
        #expect(Set(ids).count == ids.count)                        // no duplicate ids across pages
    }

    @Test func collectAllPages_single_page_stops_when_cursor_nil() async throws {
        var calls = 0
        let collected = try await SharedDeckCatalogService.collectAllPages { _ in
            calls += 1
            return self.listPage(0..<3, nextCursor: nil)
        }
        #expect(calls == 1)          // nil cursor → exactly one fetch
        #expect(collected.summaries.count == 3)
        #expect(collected.truncated == false)   // drained authoritatively
    }

    @Test func collectAllPages_caps_pages_on_looping_cursor_marks_truncated() async throws {
        // Degenerate server that never yields a nil cursor → must not loop forever,
        // AND the partial union it returns must be flagged truncated (non-authoritative)
        // so reconcile is skipped — else decks past the cap get mass-tombstoned.
        var calls = 0
        let collected = try await SharedDeckCatalogService.collectAllPages(maxPages: 3) { _ in
            calls += 1
            return SharedDeckListResponse(decks: [self.summary("d\(calls)")], nextCursor: "always")
        }
        #expect(calls == 3)                      // hard cap honoured
        #expect(collected.summaries.count == 3)
        #expect(collected.truncated == true)     // cap hit → partial set is NON-authoritative
    }

    @Test func collectAllPages_empty_page_with_cursor_marks_truncated() async throws {
        // A defensive empty page carrying a live cursor stops pagination — but the
        // accumulated union is partial (page-2+ never fetched), so it MUST be flagged
        // truncated, symmetric with the cap-hit and throwing-fetch paths.
        let page0 = listPage(0..<20, nextCursor: "c1")            // real decks, more to come
        let page1 = SharedDeckListResponse(decks: [], nextCursor: "c1")  // empty + live cursor
        let collected = try await SharedDeckCatalogService.collectAllPages { cursor in
            cursor == nil ? page0 : page1
        }
        #expect(collected.summaries.count == 20)   // still upserts what it fetched
        #expect(collected.truncated == true)       // empty-with-cursor → NON-authoritative
    }

    // MARK: - applyCatalog: authoritative-vs-truncated reconcile gate
    //
    // syncAll delegates its post-fetch work to `applyCatalog`. A drained
    // collection reconciles (tombstones absent decks); a truncated one upserts
    // but MUST skip reconcile — the symmetry that closes the mass-delete class
    // previously hidden behind the cap-hit / empty-page break paths.

    @Test func applyCatalog_drained_reconciles_and_tombstones_absent_deck() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1"), sortOrder: 0, context: ctx)
        SharedDeckCatalogService.upsertDeck(summary: summary("d2"), sortOrder: 1, context: ctx)
        try ctx.save()

        // Authoritative (not truncated) set that omits d2 → d2 must tombstone.
        let ran = SharedDeckCatalogService.applyCatalog(
            .init(summaries: [summary("d1")], truncated: false), context: ctx
        )
        try ctx.save()

        #expect(ran == true)   // reconcile ran
        let byId = Dictionary(uniqueKeysWithValues: try decks(ctx).map { ($0.remoteId, $0) })
        #expect(byId["d2"]?.isSoftDeleted == true)
    }

    @Test func applyCatalog_truncated_skips_reconcile_and_keeps_absent_deck() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        SharedDeckCatalogService.upsertDeck(summary: summary("d1"), sortOrder: 0, context: ctx)
        SharedDeckCatalogService.upsertDeck(summary: summary("d2"), sortOrder: 1, context: ctx)
        try ctx.save()

        // Truncated set omitting d2: reconcile MUST be skipped so d2 survives.
        // This is the nit-1 fix — the cap-hit / empty-page break paths used to
        // feed this partial union to reconcile and tombstone d2.
        let ran = SharedDeckCatalogService.applyCatalog(
            .init(summaries: [summary("d1")], truncated: true), context: ctx
        )
        try ctx.save()

        #expect(ran == false)   // reconcile skipped
        let byId = Dictionary(uniqueKeysWithValues: try decks(ctx).map { ($0.remoteId, $0) })
        #expect(byId["d2"]?.isSoftDeleted == false, "truncated set must not tombstone decks past the truncation point")
        // The fetched deck is still upserted so the user sees what we did get.
        #expect(byId["d1"]?.isSoftDeleted == false)
    }

    @Test func collectAllPages_propagates_mid_pagination_fetch_error() async {
        // A page fetch that throws must propagate so `syncAll` returns
        // `.listFetchFailed` and skips reconcile — a partial set is not
        // authoritative and must never drive a mass-delete.
        await #expect(throws: URLError.self) {
            _ = try await SharedDeckCatalogService.collectAllPages { cursor in
                if cursor == nil {
                    return self.listPage(0..<20, nextCursor: "c1")   // page 1 OK, more to come
                }
                throw URLError(.timedOut)                            // page 2 fails
            }
        }
    }

    // Integration: page a 2-page catalog, then apply exactly what `syncAll`
    // does post-fetch (upsert every accumulated deck + reconcile against the
    // SAME full set). The second-page deck must survive — this is the bug fix.
    @Test func multiPage_sync_keeps_second_page_deck_alive() async throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let page0 = listPage(0..<20, nextCursor: "c1")
        let page1 = listPage(20..<25, nextCursor: nil)
        let collected = try await SharedDeckCatalogService.collectAllPages { cursor in
            switch cursor {
            case .none: return page0
            case .some("c1"): return page1
            default: throw URLError(.badServerResponse)
            }
        }
        #expect(collected.truncated == false)   // drained → authoritative → reconcile runs
        SharedDeckCatalogService.applyCatalog(collected, context: ctx)
        try ctx.save()

        let all = try decks(ctx)
        let deckX = all.first { $0.remoteId == "d24" }    // page-2-only deck
        #expect(deckX != nil)
        #expect(deckX?.isSoftDeleted == false)            // NOT tombstoned
        #expect(all.count == 25)                          // exactly one row per deck
        #expect(all.filter { !$0.isSoftDeleted }.count == 25)
    }
}
#endif
