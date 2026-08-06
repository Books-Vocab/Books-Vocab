//
//  KGService+Sync.swift
//  Books & Vocab
//

import Foundation
import SwiftData

// MARK: - Sync

extension KGService {

    private static let readerVisibilityMigrationKey = "kg_dictionary_reader_visibility_migrated_v1"

    /// Flush reader visibility before any pull. Local intent remains durable on
    /// failure and `BackgroundSyncActor` refuses to overwrite it with the
    /// server projection until the exact desired value is acknowledged.
    func flushReaderVisibilityOutbox(container: ModelContainer) async throws {
        guard claimReaderVisibilityFlush() else { return }
        let actor = BackgroundSyncActor(modelContainer: container)
        do {
            repeat {
                if !UserDefaults.standard.bool(forKey: Self.readerVisibilityMigrationKey) {
                    try await actor.markLegacyHiddenCardsForReaderVisibilityMigration()
                }
                let edits = try await actor.pendingReaderVisibilityEdits()
                for edit in edits {
                    do {
                        _ = try await updateReaderVisibility(
                            cardId: edit.cardID,
                            readerHidden: edit.hidden
                        )
                        try await actor.markReaderVisibilitySynced(
                            cardID: edit.cardID,
                            hidden: edit.hidden
                        )
                    } catch KGError.httpError(let statusCode, _) where statusCode == 404 {
                        // Rolling backend: preserve the durable intent without
                        // blocking legacy vocab sync. A later sync retries it.
                        UserDefaults.standard.set(
                            true, forKey: Self.readerVisibilityMigrationKey
                        )
                        abortReaderVisibilityFlush()
                        return
                    }
                }
                UserDefaults.standard.set(true, forKey: Self.readerVisibilityMigrationKey)
            } while finishReaderVisibilityFlushPass()
        } catch {
            abortReaderVisibilityFlush()
            throw error
        }
    }

    func pullDictionaryCardsToLocal(
        container: ModelContainer,
        since: String?,
        notebookId: String?
    ) async throws {
        let actor = BackgroundSyncActor(modelContainer: container)
        var cursor: String?
        repeat {
            let page = try await fetchDictionaryCards(
                since: since, notebookId: notebookId, cursor: cursor
            )
            try await actor.upsertDictionaryProjections(page.cards)
            cursor = page.nextCursor
        } while cursor != nil
    }

    // MARK: - Push Review State

    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) {
        let actor = BackgroundSyncActor(modelContainer: container)
        // Captured before the payload is built so a review landing mid-request
        // stays dirty rather than being acknowledged as already-sent.
        let boundary = Date()
        let payload = try await actor.buildReviewStatePushPayload()
        guard !payload.isEmpty else { return (0, 0) }

        struct PushResponse: Decodable {
            let updated: Int
            let skipped: Int
        }
        let result = try await authenticatedDecode(
            PushResponse.self,
            path: "api/vocab/review",
            method: "PATCH",
            body: try JSONSerialization.data(withJSONObject: ["entries": payload])
        )
        try await actor.markReviewStatesPushed(upTo: boundary)
        AppLog.kg.info("pushReviewStates: sent=\(payload.count), updated=\(result.updated), skipped=\(result.skipped)")
        return (result.updated, result.skipped)
    }

    // MARK: - Offline KG Sync logic

    /// Pull server cards into the local store, serialized against other pulls.
    ///
    /// Two properties this wrapper buys, both of which the bare implementation
    /// lacked:
    ///
    /// 1. **Serialization.** A pull waits for any pull already in flight before
    ///    issuing its own `GET /api/vocab`, so no two requests go out carrying
    ///    the same `?since=` cursor and the same payload is never merged twice.
    ///    Every caller still gets its own request — see `KGService.enqueuePull`
    ///    for why sharing one response would be wrong.
    ///
    /// 2. **Immunity to view lifecycle.** The work runs in an unstructured `Task`,
    ///    which inherits priority and actor context but *not* cancellation. A pull
    ///    started from `.task`/`.refreshable` therefore survives the view being
    ///    torn down or re-rendered mid-flight. That teardown used to cancel the
    ///    in-flight `URLSession` request, surface `-999` as "網路錯誤：已取消", and
    ///    throw away a sync that had already paid for its round trip.
    ///
    /// The caller's own cancellation is honoured at the boundary instead: callers
    /// that go away stop waiting (see the `Task.checkCancellation` in
    /// `KGVocabCoordinator`), while the sync itself runs to completion.
    @discardableResult
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)? = nil, notebookId: String? = nil) async throws -> KGPullOutcome {
        try await pullCardsToLocal(
            container: container, progress: progress, notebookId: notebookId, reporter: nil
        )
    }

    /// `pullCardsToLocal` 加上逐步進度回報。
    ///
    /// 為什麼字典卡的回報必須從這裡出去：字典卡投影是 `performPullCardsToLocal`
    /// **內部**的一段（在單字卡 merge 之後、推進 `incrementalBoundary` 之前），
    /// 兩者共用同一個 `since` 游標與同一個 boundary 決策。把它拉到外面變成獨立的
    /// 一步會改動那個契約，代價遠大於「讓 UI 多一列」的收益。所以改成讓這支在
    /// 內部把 `.pull` 收尾、再開 `.dictionary`，UI 看到的順序才與實際執行順序一致。
    ///
    /// `reporter` 沒有預設值：它與上面那支三參數版構成 overload，給了預設值會讓
    /// 兩者在只傳 container 時互相打架。
    @discardableResult
    func pullCardsToLocal(
        container: ModelContainer,
        progress: ((String, Int, Int) -> Void)?,
        notebookId: String?,
        reporter: SyncProgressReporting?
    ) async throws -> KGPullOutcome {
        let task = enqueuePull { predecessor, pullID in
            Task {
                defer { self.finishPull(id: pullID) }
                // Wait out the predecessor, but never inherit its fate: a failed
                // or cancelled earlier pull must not fail this one. `result`
                // swallows both outcomes by construction.
                _ = await predecessor?.result
                return try await self.performPullCardsToLocal(
                    container: container, progress: progress,
                    notebookId: notebookId, reporter: reporter
                )
            }
        }
        return try await task.value
    }

    private func performPullCardsToLocal(
        container: ModelContainer,
        progress: ((String, Int, Int) -> Void)?,
        notebookId: String?,
        reporter: SyncProgressReporting?
    ) async throws -> KGPullOutcome {
        progress?(L10n.string("正在下載單字..."), 0, 0)

        let defaults = UserDefaults.standard
        let storedPayloadVersion = defaults.integer(forKey: SyncKeys.payloadVersion)
        if storedPayloadVersion < SyncKeys.currentPayloadVersion {
            defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
            progress?(L10n.string("升級卡片資料格式，重新同步全部卡片..."), 0, 0)
        }

        var lastSyncMillis = defaults.double(forKey: SyncKeys.incrementalBoundary)
        // Safety: if boundary exists but local store is empty, force full sync.
        // This handles Xcode rebuild (clears SQLite but not UserDefaults),
        // interrupted syncs, or any other boundary/data mismatch.
        if lastSyncMillis > 0 {
            let actor = BackgroundSyncActor(modelContainer: container)
            let localCount = try await actor.syncedEntryCount()
            if localCount == 0 {
                AppLog.kg.warning("Incremental boundary exists but local store is empty — forcing full sync")
                defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
                lastSyncMillis = 0
            }
        }
        let isIncremental = lastSyncMillis > 0

        var queryItems: [URLQueryItem] = []
        if let notebookId {
            queryItems.append(URLQueryItem(name: "notebook_id", value: notebookId))
        }
        if isIncremental {
            let dateString = AppDateFormatters.iso8601.string(from: Date(timeIntervalSince1970: lastSyncMillis))
            queryItems.append(URLQueryItem(name: "since", value: dateString))
            AppLog.kg.info("Performing incremental sync since: \(dateString)")
        } else {
            AppLog.kg.info("Performing full sync")
        }

        // Bug A fix: 記錄邊界在發起請求前，避免 pull 期間新增的卡片被跳過
        let pullBoundary = Date().timeIntervalSince1970

        // Preserve a user's local visibility choice across the server-authority
        // migration before either projection can overwrite it.
        try await flushReaderVisibilityOutbox(container: container)

        let (data, httpResponse) = try await authenticatedRequest(
            path: "api/vocab",
            queryItems: queryItems.isEmpty ? nil : queryItems
        )

        guard httpResponse.statusCode == 200 else {
            throw KGError.httpError(statusCode: httpResponse.statusCode, detail: "GET api/vocab failed")
        }

        progress?(L10n.string("解析資料..."), 0, 0)
        let fetchedCards: [KGCard]
        do {
            fetchedCards = try JSONDecoder().decode([KGCard].self, from: data)
        } catch {
            AppLog.kg.error("Failed to decode KG cards: \(error.localizedDescription)")
            throw KGError.serverError("Parse error: \(error.localizedDescription)")
        }

        let actor = BackgroundSyncActor(modelContainer: container)
        let pullResult = try await actor.pullCardsToLocal(
            fetchedCards: fetchedCards,
            isIncremental: isIncremental,
            progress: { detail, current, total in
                progress?(detail, current, total)
            },
            notebookId: notebookId ?? "default"
        )

        // 單字卡這一步在此收尾——下面的字典卡投影是另一件事，讓它們在 UI 上同時
        // 顯示為 running 會謊報平行度（它們是嚴格序列的，理由見 backgroundSync）。
        reporter?(.finished(.pull, status: .done, detail: Self.pullDetail(
            inserted: pullResult.inserted, updated: pullResult.updated, deleted: pullResult.deleted
        )))

        reporter?(.started(.dictionary))
        do {
            try await pullDictionaryCardsToLocal(
                container: container,
                since: isIncremental
                    ? AppDateFormatters.iso8601.string(from: Date(timeIntervalSince1970: lastSyncMillis))
                    : nil,
                notebookId: notebookId
            )
            reporter?(.finished(.dictionary, status: .done, detail: ""))
        } catch KGError.httpError(let statusCode, _) where statusCode == 404 {
            // Rolling-upgrade compatibility: legacy backend has no dictionary
            // projection yet. Learning-card sync remains available.
            AppLog.sync.info("Dictionary projection unavailable on legacy backend")
            reporter?(.finished(.dictionary, status: .skipped, detail: L10n.string("此伺服器尚未提供字典卡")))
        } catch is CancellationError {
            // 取消不畫紅叉（與 `legFinishedEvent` 同一條契約）。走 generic catch 的話
            // 除了誤標失敗，`CancellationError().localizedDescription` 還會把英文的
            // "The operation couldn't be completed." 原封送上 zh-Hant / ja / ko 的設定頁。
            reporter?(.finished(.dictionary, status: .skipped, detail: ""))
            throw CancellationError()
        } catch {
            // 非 404 一律往外拋（維持既有語意：字典卡壞掉 = 整條 pull 失敗）。
            // 先回報再 rethrow，否則這一列會停在 running 直到下一輪覆寫。
            reporter?(.finished(.dictionary, status: .error, detail: SyncFailurePresentation.reason(for: error)))
            throw error
        }

        // Orphan cleanup leak fix: when a full sync's orphan cleanup was
        // blocked by the mass-deletion safety valve, the local store still
        // holds ghost entries. Advancing the boundary here would lock all
        // future syncs into incremental mode — which never runs cleanup —
        // so the ghosts would never be reaped. Instead, clear the boundary
        // so the next sync runs a full sync again and retries the cleanup.
        if pullResult.orphanCleanupBlocked {
            defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
            AppLog.kg.warning("Incremental boundary NOT advanced: orphan cleanup was blocked — next sync will retry full sync")
        } else {
            defaults.set(pullBoundary, forKey: SyncKeys.incrementalBoundary)
        }
        defaults.set(SyncKeys.currentPayloadVersion, forKey: SyncKeys.payloadVersion)

        return KGPullOutcome(
            pipelinePending: httpResponse.value(forHTTPHeaderField: "X-Pipeline-Pending") == "true",
            inserted: pullResult.inserted,
            updated: pullResult.updated,
            deleted: pullResult.deleted
        )
    }

    func clearLocalData(container: ModelContainer, reason: String = "unspecified") async {
        let actor = BackgroundSyncActor(modelContainer: container)
        AppLog.kg.info("clearLocalData requested. reason=\(reason)")
        do {
            try await actor.clearUserData(reason: reason)
        } catch {
            AppLog.kg.error("clearUserData failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "kg.local.clear")
        }

        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
        defaults.removeObject(forKey: SyncKeys.reviewEventPullBoundary)
        defaults.removeObject(forKey: SyncKeys.payloadVersion)
        ActiveNotebookStore.shared.clear()
        defaults.removeObject(forKey: NotebookFilter.storageKey)
        lastSyncDate = nil
        Self.persistLastSyncDate(nil)
        serverCardCount = 0
    }

    // MARK: - Background Sync (輕量：push review + pull)

    /// 將一個可拋錯的 async 操作包成 `Result`，供 `async let` 並行收集 —
    /// 取代各 phase 重複的 do/catch 立即執行閉包，保留 child task 並行語意。
    ///
    /// 泛型化（原本固定 `Void`）是為了讓進度回報拿得到各步驟的筆數：一列寫
    /// 「已送出 0 筆」與寫「已送出 47 筆」的資訊量差距，正是複習紀錄重送那個 bug
    /// 當初沒被任何人看見的原因。`processSyncPhase` 仍只吃 `Result<Void, Error>`，
    /// 呼叫端用 `.map { _ in () }` 抹掉型別後交進去。
    private static func captureResult<T: Sendable>(
        _ operation: @escaping @Sendable () async throws -> T
    ) async -> Result<T, Error> {
        do {
            return .success(try await operation())
        } catch {
            return .failure(error)
        }
    }

    /// 這一輪 `backgroundSync` 會回報的步驟，順序即 UI 顯示順序。
    ///
    /// 由服務自己宣告而不是讓 UI 猜：UI 必須先知道完整清單才畫得出「還沒輪到」的
    /// 灰列與正確的進度條分母，而唯一知道自己會跑哪幾段的是這裡。清單與實作因此
    /// 只有一個真相；`podcastEnabled` 參數化只供測試釘語意，production 走預設值。
    static func syncStepIDs(
        podcastEnabled: Bool = KGFeatureFlags.podcastEnabled
    ) -> [SyncStepID] {
        var ids: [SyncStepID] = [.push, .pull, .dictionary, .reviewEvents]
        if podcastEnabled { ids.append(.podcast) }
        return ids
    }

    /// `.pull` 完成列的說明文字。無變更時明講「已是最新」——留白會讓使用者以為
    /// 那一步沒跑完。用「同步」而不是「更新」：這個數字含新增與刪除，只刪了 3 張卡
    /// 的一輪寫「更新 3 筆」是錯的。
    static func pullDetail(inserted: Int, updated: Int, deleted: Int) -> String {
        let changed = inserted + updated + deleted
        guard changed > 0 else { return L10n.string("已是最新") }
        return L10n.format("同步 %@ 筆", "\(changed)")
    }

    /// `.push` 完成列的說明文字。
    ///
    /// **算的是「送出了幾筆」，不是「伺服器接受了幾筆」。** 兩者都要含 `skipped`：
    /// 伺服器端去重把重複的算 skipped，只看 updated / inserted 的話，複習紀錄
    /// 重送那個 bug（每輪重推 9,580 筆、伺服器全判重複）會顯示「已送出 0 筆」——
    /// 跟修好之前一模一樣，這一列就白加了。
    static func pushDetail(states: (updated: Int, skipped: Int), events: (inserted: Int, skipped: Int)) -> String {
        let sent = states.updated + states.skipped + events.inserted + events.skipped
        return L10n.format("已送出 %@ 筆", "\(sent)")
    }

    /// 一般單腿的收尾事件：成功 `.done`、取消 `.skipped`、其餘 `.error`。
    ///
    /// 取消刻意不畫紅叉——使用者離開畫面把 task 收掉不是錯誤，畫紅的只會讓下一次
    /// 有人來問「同步壞了嗎」。這與 `processSyncPhase` 對 `CancellationError`
    /// 的處置同義（那裡也不計入 failures）。
    static func legFinishedEvent<T>(
        _ id: SyncStepID,
        result: Result<T, Error>,
        detail: String
    ) -> SyncProgressEvent {
        switch result {
        case .success:
            return .finished(id, status: .done, detail: detail)
        case .failure(let error) where error is CancellationError:
            return .finished(id, status: .skipped, detail: "")
        case .failure(let error):
            return .finished(id, status: .error, detail: SyncFailurePresentation.reason(for: error))
        }
    }

    /// push 那一列的收尾。兩腿併發、共用一列，所以任一腿失敗即整列失敗；
    /// 兩腿都成功才把筆數寫進 detail。
    static func pushFinishedEvent(
        states: Result<(updated: Int, skipped: Int), Error>,
        events: Result<(inserted: Int, skipped: Int), Error>
    ) -> SyncProgressEvent {
        guard case .success(let s) = states else {
            return legFinishedEvent(.push, result: states, detail: "")
        }
        guard case .success(let e) = events else {
            return legFinishedEvent(.push, result: events, detail: "")
        }
        return .finished(.push, status: .done, detail: pushDetail(states: s, events: e))
    }

    /// podcast 那一列的收尾。
    ///
    /// `nil` = feature flag 關著，這一步根本沒被宣告，回一個對未宣告步驟的事件
    /// （store 會丟棄）比回 `.skipped` 誠實——Release 使用者的清單裡沒有這一列。
    ///
    /// **`.listFetchFailed` 只染紅這一列，不進 `failureMessages`。** 那個欄位會
    /// 讓整輪判定為部分失敗、`lastSyncDate` 不前進、設定頁彈出「背景同步部分失敗」。
    /// 讓 podcast 目錄的一次 hiccup 把「上次同步時間」凍住，對使用者是明確的退步；
    /// 而現在有了逐步清單，那一列自己會紅——可見性已經拿到了，不需要再借用一個
    /// 語意更重的欄位。
    static func podcastFinishedEvent(
        _ outcome: PodcastSyncService.SyncOutcome?
    ) -> SyncProgressEvent {
        switch outcome {
        case .completed, .none:
            return .finished(.podcast, status: .done, detail: "")
        case .cancelled:
            return .finished(.podcast, status: .skipped, detail: "")
        case .listFetchFailed:
            return .finished(.podcast, status: .error, detail: L10n.string("目錄讀取失敗"))
        }
    }

    /// 處理單一 backgroundSync phase 的並行結果，統一處理 401 / log / Sentry /
    /// CancellationError 過濾。回傳該 phase 的 failure label + UI message；若遇到 401
    /// 則已內部處理 handleUnauthorized + lastBackgroundSyncError 並回傳 nil
    /// 以通知 caller 直接 return。
    /// internal（原本 private）純粹是為了讓測試看得到。這三個型別 + `processSyncPhase`
    /// 是 backgroundSync 唯一的失敗分類邏輯——401 短路、取消不算失敗、部分失敗聚合——
    /// 在此之前**一個測試都沒有**，而它決定使用者看到「登入已過期」還是「部分失敗」
    /// 還是什麼都不看到。經 `backgroundSync` 端到端反推這三條分支需要真網路，
    /// 那才是真正的壞主意。
    struct SyncPhaseFailure {
        let label: String
        let message: String
    }

    /// Outcome of one `backgroundSync` phase. `cancelled` is tracked separately
    /// from `failures` because a cancelled leg is neither a success nor a
    /// failure — see `backgroundSync`'s terminal handling.
    struct SyncPhaseOutcome {
        var failures: [SyncPhaseFailure] = []
        var cancelled = false
    }

    func processSyncPhase(
        results: [Result<Void, Error>],
        labels: [String],
        container: ModelContainer
    ) async -> SyncPhaseOutcome? {
        var outcome = SyncPhaseOutcome()
        for (result, label) in zip(results, labels) {
            guard case .failure(let error) = result else { continue }
            // A cancelled leg is not a failed leg — reporting it would put
            // "背景同步部分失敗" in front of a user whose only crime was leaving the
            // screen. But it is not a *successful* leg either, so it is recorded
            // rather than dropped: the caller must not go on to claim the round
            // succeeded (that would toast「同步完成」for work that never ran).
            if error is CancellationError {
                AppLog.kg.info("backgroundSync \(label) cancelled")
                outcome.cancelled = true
                continue
            }
            if error is KGError, case KGError.unauthorized = error {
                await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
                lastBackgroundSyncError = L10n.string("登入已過期")
                return nil
            }
            AppLog.kg.warning("backgroundSync \(label) failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "kg.sync.\(label)")
            outcome.failures.append(SyncPhaseFailure(
                label: label,
                message: SyncFailurePresentation.message(label: label, error: error)
            ))
        }
        return outcome
    }

    func backgroundSync(container: ModelContainer) async {
        await backgroundSync(container: container, progress: nil)
    }

    func backgroundSync(container: ModelContainer, progress: SyncProgressReporting?) async {
        // 防止併發：快速前景/背景切換可能觸發多個 sync task
        guard claimBackgroundSync() else {
            AppLog.kg.info("backgroundSync skipped: already in progress")
            return
        }
        defer { releaseBackgroundSync() }

        // 每輪開始即重置 error-tracking 欄位：四個 trigger（post-login / scenePhase
        // / ⌘R menu / Settings 手動）共用此全域欄位，read-then-clear consumer 有
        // 三處（App 層 scenePhase 兩處 + ExplicitSync）。claim 鎖已序列化整段
        // （同時間僅一輪執行），於 claim 成功後、
        // cleanup gate 懸掛前清空 —— gate 可懸掛數秒，期間被 skip 的 trigger 會立即
        // read-then-clear，必須讀不到上一輪 stale 值（典型：logout-401 留下的「登入
        // 已過期」在重登成功後反彈成過期 toast）。失敗時下方會再 set 為本輪正確值。
        lastBackgroundSyncError = nil

        // 先等 logout 排程的本地清理收尾，再動任何 sync 工作。否則快速
        // 「登出→重登」會讓 sync 搶用尚未被清的 sync boundary（incremental
        // 跳過後端全部卡 → 本地空庫但自認最新），且拉回的資料會被 resume 的
        // cleanup 再清一遍 —— 2026-06-09 000287 單字本事故根因。放在入口
        // 單點守住全部四個觸發點（post-login / scenePhase / ⌘R / Settings）。
        await sessionInvalidator.waitForPendingLocalDataCleanup()

        // 離線時跳過整個背景同步，不產生無意義的錯誤日誌
        guard NetworkMonitor.shared.isConnected else {
            AppLog.kg.info("backgroundSync skipped: offline")
            lastBackgroundSyncError = L10n.string("目前沒有網路連線，背景同步已跳過")
            return
        }

        AppCrashReporting.addBreadcrumb(category: "sync", message: "sync.start")
        var failureMessages: [String] = []
        var failureLabels: [String] = []
        var wasCancelled = false

        // Podcast catalog 從整輪的最前面就起跑，與底下整條 vocab 管線併行。
        //
        // 它以前排在最後、序列執行，而 2026-08-06 的生產量測說那是整輪 7.55s 裡的
        // 6.08s（81%）——同時資料量只有約 7 KB。貴的是往返次數不是位元組，而那些
        // 往返完全不需要等 vocab。兩邊零欄位重疊（PodcastSeries/Episode/Progress
        // vs VocabularyEntry/ReviewRecord），沒有任何理由讓它們互等。
        //
        // 用 `async let` 而不是 Task：早退路徑（401 / cancelled）離開 scope 時，
        // 結構化併發會自動取消並等待這個 child，不會留下背景在跑的孤兒。
        async let podcastLeg = Self.runPodcastLeg(
            container: container, kgService: self, progress: progress
        )

        // Phase 1: push review states & review events in parallel
        progress?(.started(.push))
        async let pushReviewResult = Self.captureResult { try await self.pushReviewStates(container: container) }
        async let pushEventsResult = Self.captureResult { try await self.pushReviewEvents(container: container) }

        let pushStates = await pushReviewResult
        let pushEvents = await pushEventsResult
        let pushResults = [pushStates.map { _ in () }, pushEvents.map { _ in () }]
        progress?(Self.pushFinishedEvent(states: pushStates, events: pushEvents))
        if let pushOutcome = await processSyncPhase(
            results: pushResults, labels: ["pushReview", "pushReviewEvents"], container: container
        ) {
            failureMessages.append(contentsOf: pushOutcome.failures.map(\.message))
            failureLabels.append(contentsOf: pushOutcome.failures.map(\.label))
            wasCancelled = wasCancelled || pushOutcome.cancelled
        } else {
            return
        }

        // Phase 2: pull cards & review events in parallel (after push completes)
        //
        // **push → pull 必須序列。** pull 會把伺服器的 `lastReviewedAt` 寫回本地；
        // 先拉再送會讓「還沒送出」的基準被覆蓋掉（7a8352f27 有測試釘住）。
        //
        // **單字卡 pull 與字典卡 pull 也必須序列，這點違反直覺所以寫下來。**
        // `BackgroundSyncActor` 是 `@ModelActor`，但它在 12 個 call site 各自 init，
        // 每個實例有自己的 `ModelContext` —— actor 隔離只序列化「對同一實例」的呼叫，
        // 不會序列化兩個不同實例。而 `pullCardsToLocal` 與 `upsertDictionaryProjections`
        // 都 fetch 全部 `VocabularyEntry`、都寫 translation / explanation / isArchived
        // / cardRole / markSynced() 這幾乎相同的一組欄位。併發的後果具體有五個：
        // 兩個 context 的 lost update、同一 mergeKey 重複插入、mass-deletion 安全閥
        // 讀到會動的分母（而它決定 incrementalBoundary 要不要前進）、
        // `reviewMergeEqualInstantConflicts` 這個 nonisolated(unsafe) static 的真實
        // data race，以及 `SyncKeys.incrementalBoundary` 是單一全域 key（`enqueuePull`
        // 全域序列化的原因也在此）。所以字典卡留在 pull 內部序列跑，不要「順手併發」。
        //
        // `.pull` 與 `.dictionary` 的收尾事件由 `performPullCardsToLocal` 內部發出
        // （字典卡投影是它的一段，見那支的說明）；這裡只負責開場與失敗時的補救。
        progress?(.started(.pull))
        progress?(.started(.reviewEvents))
        // `progress:` 這條線一直都在（`pullCardsToLocal` 從第一天就收 progress
        // 閉包），只是 backgroundSync 一直傳 nil —— 線留著沒接。接上它，`.pull`
        // 那一列才有真實的 current/total，進度條在整段同步最長的一步裡才會動。
        async let pullCardsResult = Self.captureResult {
            try await self.pullCardsToLocal(
                container: container,
                progress: { detail, current, total in
                    progress?(.advanced(.pull, current: current, total: total, detail: detail))
                },
                notebookId: nil,
                reporter: progress
            )
        }
        async let pullEventsResult = Self.captureResult { try await self.pullReviewEvents(container: container) }

        let pullCards = await pullCardsResult
        let pullEvents = await pullEventsResult
        let pullResults = [pullCards.map { _ in () }, pullEvents.map { _ in () }]
        // 失敗時 `.pull` 停在 running（內部的收尾事件沒走到），這裡補一個終態。
        //
        // **取消也要補。** `KGService+Request` 會把 URLError -999 轉成
        // `CancellationError`，所以 `api/vocab` 這個 GET 真的產得出取消；漏掉這條
        // 分支的話 `.pull` 會停在轉圈，而 `wasCancelled` 早退後再也不會有事件來救它。
        //
        // **`.dictionary` 不補。** 它的 do/catch 涵蓋了自己 started 之後的每一條
        // 出口，所以它要嘛已終態、要嘛從沒開始過——沒開始過的是 `.waiting`（灰列），
        // 不會轉圈。硬補一個 `.error` 只會讓「單字卡第一步就死」的那一輪憑空把
        // 字典卡的權重算滿，進度條顯示 80%。store 端的「首個終態說了算」讓成功路徑
        // 上這裡的重複發送無害，但無害不等於該發。
        if case .failure(let error) = pullCards {
            progress?(error is CancellationError
                ? .finished(.pull, status: .skipped, detail: "")
                : .finished(.pull, status: .error, detail: SyncFailurePresentation.reason(for: error)))
        }
        progress?(Self.legFinishedEvent(.reviewEvents, result: pullEvents, detail: ""))
        if let pullOutcome = await processSyncPhase(
            results: pullResults, labels: ["pull", "pullReviewEvents"], container: container
        ) {
            failureMessages.append(contentsOf: pullOutcome.failures.map(\.message))
            failureLabels.append(contentsOf: pullOutcome.failures.map(\.label))
            wasCancelled = wasCancelled || pullOutcome.cancelled
        } else {
            return
        }

        // Cancelled = the round never finished, so it is neither success nor
        // failure. Returning here keeps `lastSyncDate` where it was and leaves
        // `lastBackgroundSyncError` nil; `ExplicitSync` reads `Task.isCancelled`
        // to know it must stay silent rather than toast「同步完成」for a sync that
        // was abandoned. Nothing is lost — a cancelled pull never advanced its
        // cursor, so the next round redoes exactly this work.
        if wasCancelled {
            AppLog.kg.info("backgroundSync ended cancelled — lastSyncDate not advanced")
            AppCrashReporting.addBreadcrumb(
                category: "sync", message: "sync.end.cancelled", level: .info
            )
            return
        }

        // 收 podcast 那條併行的腿。它從整輪最前面就在跑（見上方 `async let`），
        // 到這裡多半早就結束了 —— 這行只是把它的結果取回來畫那一列。
        //
        // 為什麼 podcast 屬於 backgroundSync 而不是書架自己的 .task：它要共用全部
        // 四個既有觸發（post-login / scenePhase→active / ⌘R menu / Settings 手動），
        // 補上「Mac Catalyst 下 .refreshable 不可用、BookshelfView .task 每 view
        // identity 只跑一次」造成的、書架 podcast 區塊一旦沒載入就無法復原的缺口。
        //
        // syncAll 自我防禦（list fetch 失敗即 skip、空回傳不刪 series），不 throw。
        await podcastLeg
        // 早退路徑（401 / wasCancelled）不會走到這裡，那時 `async let` 的隱式取消
        // 會把這條腿收掉——podcast 目錄同步是冪等的，取消一次沒有任何後果。

        if failureMessages.isEmpty {
            lastBackgroundSyncError = nil
            let syncedAt = Date()
            lastSyncDate = syncedAt
            Self.persistLastSyncDate(syncedAt)
            AppCrashReporting.addBreadcrumb(category: "sync", message: "sync.end.success")
        } else {
            lastBackgroundSyncError = L10n.format("背景同步部分失敗：%@", failureMessages.joined(separator: ", "))
            AppCrashReporting.addBreadcrumb(
                category: "sync",
                message: "sync.end.partial",
                level: .warning,
                data: ["failures": failureLabels]
            )
        }
    }

    /// 併行的 podcast 目錄腿：開場事件 → 同步 → 收尾事件，整包給一個 `async let`。
    ///
    /// `PodcastSyncService.syncAll` 是 `@MainActor`，需以 main-actor `ModelContext`
    /// 呼叫（沿用 `BookshelfView` 既有契約：傳 mainContext，upsert 在 main actor、
    /// @Query 直接拿到更新）。整段標 `@MainActor` 使 `container.mainContext` 合法。
    ///
    /// 為什麼是 `static` 且顯式收 `kgService`：`async let` 的 initializer 會被當成
    /// `@Sendable` 閉包檢查，隱式捕捉 `self` 會把整個 `KGService` 拖進去。
    ///
    /// Release（`podcastEnabled == false`）連 `.started` 都不發 —— 那一列根本不在
    /// `syncStepIDs()` 宣告的清單裡，發了 store 也會丟棄，但不發更誠實。
    @MainActor
    private static func runPodcastLeg(
        container: ModelContainer,
        kgService: KGService,
        progress: SyncProgressReporting?
    ) async {
        guard KGFeatureFlags.podcastEnabled else { return }
        // 沒有 session 就不抓目錄。podcast browse 端點確實收 guest，但 backgroundSync
        // 只在登入狀態下被觸發——這裡看到 nil token 代表 session 已經死了，這一趟
        // 注定白跑。以前它排在 vocab pull 的 401 早退之後，等於被那個 return 順手
        // 擋掉；現在它跑在最前面，就得自己擋。讀 `authSession.token` 而不是呼叫
        // `currentAuthToken()`：後者對過期 token 會觸發 logout，拿它當前置檢查
        // 等於偷偷改了 session 失效的時機。
        guard await kgService.authSession.token != nil else { return }
        progress?(.started(.podcast))
        let outcome = await runPodcastCatalogSyncIfEnabled {
            await PodcastSyncService(kgService: kgService).syncAll(context: container.mainContext)
        }
        progress?(podcastFinishedEvent(outcome))
    }

    /// Feature-gate seam for the podcast catalog leg of `backgroundSync`.
    /// Release（`KGFeatureFlags.podcastEnabled == false`）必須零 podcast 網路/磁碟
    /// 足跡：catalog list fetch + 封面下載在建構 `PodcastSyncService` 之前就短路。
    /// `podcastEnabled` 參數化僅供測試鎖語意；production 一律走預設值。
    @MainActor
    static func runPodcastCatalogSyncIfEnabled(
        podcastEnabled: Bool = KGFeatureFlags.podcastEnabled,
        sync: @MainActor () async -> PodcastSyncService.SyncOutcome
    ) async -> PodcastSyncService.SyncOutcome? {
        guard podcastEnabled else { return nil }
        return await sync()
    }

    func pushReviewQuietly(container: ModelContainer) async {
        guard NetworkMonitor.shared.isConnected else {
            AppLog.kg.info("pushReviewQuietly skipped: offline")
            return
        }

        do {
            _ = try await pushReviewStates(container: container)
        } catch {
            AppLog.kg.warning("pushReviewQuietly failed: \(error.localizedDescription)")
        }
        do {
            _ = try await pushReviewEvents(container: container)
        } catch {
            AppLog.kg.warning("pushReviewQuietly pushReviewEvents failed: \(error.localizedDescription)")
        }
    }
}
