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

    // MARK: - Guest-tolerant browse: an expired token must not log the user out

    /// 逛公開牌組目錄**不該讓任何人登出**（backlog APP-20260805-0049ac）。
    ///
    /// 這條測試走的是真的 `KGService`（只換掉 auth 兩個縫），不是 `SpyKGService`——
    /// 因為缺陷不在 catalog service 裡，而在它**問誰要 token**：`currentAuthToken()`
    /// 判定過期時會先 `sessionInvalidator.logout(...)` 再 throw，`try?` 只吞後者。
    /// 用替身餵 token 等於把待測的失效模式從模型裡刪掉，這條測試就會永遠綠。
    @Test func testExpiredTokenBrowseDoesNotInvalidateSession() async throws {
        // Reachability 前提，但要說清楚它值多少：**修法後這道 guard 不 load-bearing**
        // （新路徑根本不碰 NetworkMonitor）。它只在有人把本函式改回 `currentAuthToken()`
        // 時才有意義——那條路徑的第一道 guard 是 reachability，離線時會在碰到過期判斷
        // 之前就丟 `.offline`，讓「沒登出」因為錯的理由成立。
        // 而且它是 **best-effort 不是斷言**：`NetworkMonitor.isConnected` 宣告即 `= true`，
        // 要等 `NWPathMonitor` 第一次 path update hop 到 MainActor 才修正，冷啟動的測試
        // 程序多半在那之前就讀到 true。別把它當成硬前提。
        try #require(
            NetworkMonitor.shared.isConnected,
            "此測試需要 reachability 為 true（best-effort：NetworkMonitor 預設即 true，斷網 runner 上可能放行）"
        )

        let invalidator = RecordingSessionInvalidator()
        let service = KGService(
            authSession: FixedTokenSession(expiresIn: -3600),
            sessionInvalidator: invalidator
        )

        let sent = try await browseCapturingRequest(marker: "expired", kgService: service)

        // 1. 過期 token 不得觸發全域登出，也不得備妥那句「請重新登入」的 alert 文案。
        //    **這兩條才是抓到缺陷的斷言**：修法前它們實際收到
        //    `["logout_token_expired_precheck"]` 與「您的登入已過期，請重新登入」。
        #expect(invalidator.events.isEmpty, "browse 公開端點不得動到 session，實際：\(invalidator.events)")
        #expect(service.sessionExpiredReason == nil)
        // 2. 過期 token 等同無 token：以 guest 身分送出，不掛 Authorization。
        //    誠實標註：這條在修法前**也是綠的**（舊路徑 throw 後 `try?` 給 nil，header
        //    同樣沒掛）。它擋的是反方向的退化——別為了「省一次判斷」直接把過期 token
        //    掛上去。後端雖然容忍，但那會讓 client 對自己的 auth 狀態說謊。
        #expect(sent.value(forHTTPHeaderField: "Authorization") == nil)
    }

    /// 對稱的正向契約：**有效 token 仍然必須被掛上**。
    ///
    /// 少了這條，把 `authTokenWithoutInvalidation()` 整個改成 `{ nil }` 也能全綠——
    /// 「永遠不掛 header」是上面那條負向斷言的合法解。一組只釘負向的測試，等於默許
    /// 把功能關掉當作修好。
    @Test func testValidTokenBrowseStillSendsBearer() async throws {
        let invalidator = RecordingSessionInvalidator()
        let authSession = FixedTokenSession(expiresIn: 3600)   // 遠大於 JWTExpiry 的 60s margin
        let service = KGService(authSession: authSession, sessionInvalidator: invalidator)

        let sent = try await browseCapturingRequest(marker: "valid", kgService: service)

        let token = try #require(authSession.token)
        #expect(sent.value(forHTTPHeaderField: "Authorization") == "Bearer \(token)")
        #expect(invalidator.events.isEmpty)
    }

    /// 跑一次 browse 並取回**這一次**送出的 request。
    ///
    /// `marker` 讓每個 case 有自己的 URL：探針是 static 的，用 `reset()` 清空會在兩支
    /// 測試交錯時互相洗掉（`@MainActor` 只保證不並行執行，不保證不在 await 點交錯）。
    /// 改成只追加、按 marker 取回，就沒有破壞性操作，也就沒有那個 race。
    private func browseCapturingRequest(
        marker: String, kgService: any KGServing
    ) async throws -> URLRequest {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [BrowseProbeURLProtocol.self]
        _ = try await SharedDeckCatalogService.optionallyAuthedData(
            from: "https://decks.test/api/decks?probe=\(marker)",
            kgService: kgService,
            session: URLSession(configuration: configuration)
        )
        return try #require(
            BrowseProbeURLProtocol.captured(marker: marker),
            "探針沒收到 probe=\(marker) 的 request"
        )
    }
}

// MARK: - Test doubles for the guest-browse auth contract

/// 未簽名 JWT 的最小產生器：`expiresIn` 為負即已過期（`JWTExpiry.isExpired` 為真）。
@MainActor
private final class FixedTokenSession: AuthSessionProviding {
    let isLoggedIn = true
    let token: String?

    init(expiresIn: TimeInterval) {
        let header = Data(#"{"alg":"none"}"#.utf8).base64EncodedString()
        let exp = Int(Date().addingTimeInterval(expiresIn).timeIntervalSince1970)
        let payload = Data(#"{"sub":"user","exp":\#(exp)}"#.utf8)
            .base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        self.token = "\(header).\(payload).sig"
    }
}

@MainActor
private final class RecordingSessionInvalidator: SessionInvalidating {
    private(set) var events: [String] = []
    func logout(modelContainer: ModelContainer?, reason: String) { events.append("logout_\(reason)") }
    func waitForPendingLocalDataCleanup() async { events.append("wait_for_cleanup") }
}

/// 捕捉送出去的 request 後立刻回 200，讓「掛了什麼 header」可斷言而完全不碰真網路。
///
/// 只掛在 local `URLSessionConfiguration.ephemeral` 上、**不呼叫 `URLProtocol.registerClass`**，
/// 所以 `canInit -> true` 不會污染其他測試的 session。static 收集面只追加不清空，
/// 呼叫端用 marker 取回自己那筆（見 `browseCapturingRequest`）。
private final class BrowseProbeURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var requests: [URLRequest] = []

    /// 取回帶指定 marker 的最後一筆。刻意不提供 `reset()`：清空是唯一會讓並行測試
    /// 互相破壞的操作，不存在就不必靠紀律維護。
    static func captured(marker: String) -> URLRequest? {
        lock.withLock {
            requests.last { $0.url?.query?.contains("probe=\(marker)") == true }
        }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let request = request
        Self.lock.withLock { Self.requests.append(request) }
        guard let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)
        else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(#"{"decks":[]}"#.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
#endif
