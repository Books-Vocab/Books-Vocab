//
//  SharedDeckCatalogService.swift
//  Books & Vocab
//
//  Explore 共享牌組目錄同步 —— `PodcastSyncService` 的 1:1 類比。
//
//  唯讀 mirror：guest browse（`optionallyAuthedData`）→ fetch list/detail → upsert 進
//  獨立 `SharedDeck @Model` → reconcile orphans（**empty-response mass-delete guard**：
//  空回應視為短暫 hiccup，不整片 tombstone）。browse 端點對 guest 開放，過期 token
//  也容忍（`try?` 取 token），故開 Explore 時過期 session 不會觸發 401 登出。
//
//  本階段（Phase 1b-iii 唯讀）封面走 procedural（NotebookCoverView），**無** 遠端封面
//  下載/cache —— 因此不需 podcast 那套 cover 檔案 cache + logout purge。
//

import Foundation
import SwiftData

final class SharedDeckCatalogService {
    /// Shared-deck 目錄只 host 在公開後端，故釘 `AppURLs.domain`；唯一例外是 UI-test
    /// override（隔離 world 絕不可打真實目錄，否則 reconcile 會 tombstone 掉 seed）。
    static var baseURL: String {
        #if DEBUG
        return KGService.uiTestServerURLOverride() ?? AppURLs.domain
        #else
        return AppURLs.domain
        #endif
    }

    let kgService: any KGServing

    init(kgService: any KGServing) {
        self.kgService = kgService
    }

    // MARK: - Guest-tolerant browse transport

    /// Browse fetch that tolerates an anonymous (guest) caller. Attaches the Bearer
    /// token only when one is present — logged-out users still load the catalog.
    /// `try?` on the token: a true guest has none; an expired one is swallowed here so
    /// opening Explore never trips the 401→session-invalidation path (browse is public).
    static func optionallyAuthedData(from urlString: String, kgService: any KGServing) async throws -> Data {
        guard let url = URL(string: urlString) else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        if let token = try? await kgService.currentAuthToken() {
            request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, _) = try await sharedURLSession.data(for: request)
        return data
    }

    // MARK: - Filters / query

    struct BrowseQuery: Equatable {
        var text: String?
        var category: String?
        var languagePair: String?
        /// nil = all，true = official only，false = community only（Phase 1 只有 official）。
        var official: Bool?
        var sort: String?
        var cursor: String?
        var limit: Int?

        static let recency = BrowseQuery(sort: "recency")

        /// Percent-encoded `/api/decks?…` query string（`+` → `%2B`，見 KGService.composeRequestURL）。
        func urlQueryItems() -> [URLQueryItem] {
            var items: [URLQueryItem] = []
            if let text, !text.isEmpty { items.append(.init(name: "q", value: text)) }
            if let category { items.append(.init(name: "category", value: category)) }
            if let languagePair { items.append(.init(name: "languagePair", value: languagePair)) }
            if let official { items.append(.init(name: "official", value: official ? "true" : "false")) }
            if let sort { items.append(.init(name: "sort", value: sort)) }
            if let cursor { items.append(.init(name: "cursor", value: cursor)) }
            if let limit { items.append(.init(name: "limit", value: String(limit))) }
            return items
        }
    }

    static func listURL(query: BrowseQuery) -> String {
        let fallback = "\(baseURL)/api/decks"
        return composeURL(base: fallback, items: query.urlQueryItems()) ?? fallback
    }

    /// Compose a URL string from a base + query items, encoding literal `+` in values
    /// to `%2B` (see `KGService.composeRequestURL` — servers decode `+` as space).
    static func composeURL(base: String, items: [URLQueryItem]) -> String? {
        guard var components = URLComponents(string: base) else { return nil }
        guard !items.isEmpty else { return components.url?.absoluteString }
        components.queryItems = items
        if let encoded = components.percentEncodedQuery {
            components.percentEncodedQuery = encoded.replacingOccurrences(of: "+", with: "%2B")
        }
        return components.url?.absoluteString
    }

    // MARK: - Fetch

    func fetchDeckList(query: BrowseQuery = .recency) async throws -> SharedDeckListResponse {
        let data = try await Self.optionallyAuthedData(from: Self.listURL(query: query), kgService: kgService)
        return try JSONDecoder().decode(SharedDeckListResponse.self, from: data)
    }

    func fetchDeckDetail(deckId: String) async throws -> SharedDeckDetail {
        let data = try await Self.optionallyAuthedData(
            from: "\(Self.baseURL)/api/decks/\(deckId)", kgService: kgService)
        return try JSONDecoder().decode(SharedDeckDetail.self, from: data)
    }

    func fetchDeckCards(deckId: String, cursor: String? = nil, limit: Int? = nil) async throws -> SharedDeckCardsResponse {
        let base = "\(Self.baseURL)/api/decks/\(deckId)/cards"
        var items: [URLQueryItem] = []
        if let cursor { items.append(.init(name: "cursor", value: cursor)) }
        if let limit { items.append(.init(name: "limit", value: String(limit))) }
        let urlString = Self.composeURL(base: base, items: items) ?? base
        let data = try await Self.optionallyAuthedData(from: urlString, kgService: kgService)
        return try JSONDecoder().decode(SharedDeckCardsResponse.self, from: data)
    }

    // MARK: - Sync outcome

    enum SyncOutcome: Equatable {
        case completed
        case cancelled
        case listFetchFailed
    }

    /// Full sync: page through the ENTIRE recency-sorted catalog (following the
    /// keyset cursor), upsert every deck into SwiftData, then reconcile orphans
    /// **against the complete set**. Only the list fetch is fatal (an explicit
    /// refresh no-op); everything else stays swallowed. Mirrors
    /// `PodcastSyncService.syncAll`.
    ///
    /// Paging correctness is load-bearing: `reconcileLocalState` tombstones any
    /// local deck absent from `summaries`, so `summaries` MUST be the union of
    /// every page. A single-page fetch (the pre-Phase-2b bug) tombstoned every
    /// official deck past page 1 once the central catalog exceeded one page. A
    /// page fetch that throws mid-pagination aborts the whole pass
    /// (`.listFetchFailed`) and skips reconcile — a partial set is not
    /// authoritative and must never drive a mass-delete.
    @MainActor
    @discardableResult
    func syncAll(context: ModelContext) async -> SyncOutcome {
        let summaries: [SharedDeckSummary]
        do {
            summaries = try await Self.collectAllPages { cursor in
                var query = BrowseQuery.recency
                query.cursor = cursor
                return try await self.fetchDeckList(query: query)
            }
        } catch is CancellationError {
            AppLog.kg.warning("[SharedDeckSync] list fetch cancelled")
            return .cancelled
        } catch {
            AppLog.kg.warning("[SharedDeckSync] list fetch failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "shareddeck.sync.list")
            return .listFetchFailed
        }
        for (index, summary) in summaries.enumerated() {
            Self.upsertDeck(summary: summary, sortOrder: index, context: context)
        }
        Self.reconcileLocalState(serverSummaries: summaries, context: context)
        do {
            try context.save()
        } catch {
            AppLog.kg.warning("[SharedDeckSync] context save failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "shareddeck.sync.save")
        }
        NotificationCenter.default.post(name: .sharedDeckCatalogDidSync, object: nil)
        return .completed
    }

    /// Follow the keyset cursor across every browse page and return the union of
    /// all decks. `fetchPage(cursor)` fetches one page (`nil` cursor = first
    /// page). Pagination terminates when the server returns `nextCursor == nil`,
    /// on a defensive empty page carrying a non-nil cursor, or at `maxPages`
    /// (guards a degenerate / looping cursor — ~20/page × 50 = 1000-deck ceiling,
    /// ample for a curated official catalog). A throwing `fetchPage` propagates:
    /// the caller MUST treat a partial set as non-authoritative and skip
    /// reconcile, else page-2+ decks would tombstone.
    static func collectAllPages(
        maxPages: Int = 50,
        fetchPage: (_ cursor: String?) async throws -> SharedDeckListResponse
    ) async rethrows -> [SharedDeckSummary] {
        var accumulated: [SharedDeckSummary] = []
        var cursor: String?
        var page = 0
        while true {
            let response = try await fetchPage(cursor)
            accumulated.append(contentsOf: response.decks)
            page += 1
            cursor = response.nextCursor
            if cursor == nil { break }
            if response.decks.isEmpty {
                AppLog.kg.warning("[SharedDeckSync] empty page with non-nil cursor — stop pagination (defensive)")
                break
            }
            if page >= maxPages {
                AppLog.kg.warning("[SharedDeckSync] hit page cap \(maxPages) — stop pagination (possible cursor loop)")
                break
            }
        }
        return accumulated
    }

    // MARK: - Upsert

    @MainActor
    static func upsertDeck(summary: SharedDeckSummary, sortOrder: Int, context: ModelContext) {
        let deckId = summary.deckId
        let descriptor = FetchDescriptor<SharedDeck>(
            predicate: #Predicate { $0.remoteId == deckId }
        )
        let existing = try? context.fetch(descriptor)
        let deck: SharedDeck
        if let found = existing?.first {
            deck = found
        } else {
            deck = SharedDeck(remoteId: summary.deckId, title: summary.title)
            context.insert(deck)
        }
        deck.title = summary.title
        deck.authorLabel = summary.authorLabel
        deck.isOfficial = summary.isOfficial
        deck.category = summary.category
        deck.languagePair = summary.languagePair
        deck.tags = summary.tags
        deck.cardCount = summary.cardCount
        deck.downloadCount = summary.downloadCount
        deck.ratingAvg = summary.ratingAvg
        deck.ratingCount = summary.ratingCount
        deck.color = summary.color
        deck.coverPattern = summary.coverPattern
        deck.updatedAt = summary.updatedAt.flatMap(AppDateFormatters.parseISO8601)
        deck.sortOrder = sortOrder
        deck.syncedAt = Date()
        // Resurrect: a previously-tombstoned deck back on the server clears the flag.
        if deck.isSoftDeleted { deck.isSoftDeleted = false }
    }

    // MARK: - Reconcile (empty-response mass-delete guard)

    /// Reconcile local `SharedDeck` rows against the authoritative server list.
    /// - Local decks not on the server → soft-delete (tombstone).
    /// - Tombstoned local decks back on the server → resurrect.
    ///
    /// **Empty `serverSummaries` is treated as a transient hiccup and skipped** — a
    /// momentary empty 200 must never mass-delete the whole local catalog (symmetric
    /// to `PodcastSyncService.reconcileLocalState`'s guard).
    @MainActor
    static func reconcileLocalState(serverSummaries: [SharedDeckSummary], context: ModelContext) {
        guard !serverSummaries.isEmpty else {
            AppLog.kg.warning("[SharedDeckSync] empty server deck list — skip tombstone (avoid mass-delete on transient empty 200)")
            return
        }
        let serverIds = Set(serverSummaries.map(\.deckId))
        let allDecks = (try? context.fetch(FetchDescriptor<SharedDeck>())) ?? []
        for deck in allDecks {
            let onServer = serverIds.contains(deck.remoteId)
            if onServer && deck.isSoftDeleted {
                deck.isSoftDeleted = false
                deck.syncedAt = Date()
            } else if !onServer && !deck.isSoftDeleted {
                deck.isSoftDeleted = true
                deck.syncedAt = Date()
            }
        }
    }
}

extension Notification.Name {
    /// Posted after a successful `SharedDeckCatalogService.syncAll` reconcile so
    /// frozen-snapshot views can discretely re-read the store.
    static let sharedDeckCatalogDidSync = Notification.Name("sharedDeckCatalogDidSync")
}
