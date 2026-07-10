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
}
#endif
