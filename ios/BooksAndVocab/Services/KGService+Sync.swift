//
//  KGService+Sync.swift
//  Books & Vocab
//

import Foundation
import SwiftData

// MARK: - Sync

extension KGService {

    // MARK: - Push Review State

    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) {
        let actor = BackgroundSyncActor(modelContainer: container)
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
        AppLog.kg.info("pushReviewStates: updated=\(result.updated), skipped=\(result.skipped)")
        return (result.updated, result.skipped)
    }

    // MARK: - Offline KG Sync logic

    @discardableResult
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)? = nil, notebookId: String? = nil) async throws -> Bool {
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

        return httpResponse.value(forHTTPHeaderField: "X-Pipeline-Pending") == "true"
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
        serverCardCount = 0
    }

    // MARK: - Background Sync (輕量：push review + pull)

    /// 將一個可拋錯的 async 操作包成 `Result`，供 `async let` 並行收集 —
    /// 取代各 phase 重複的 do/catch 立即執行閉包，保留 child task 並行語意。
    private static func captureResult(_ operation: @escaping @Sendable () async throws -> Void) async -> Result<Void, Error> {
        do {
            try await operation()
            return .success(())
        } catch {
            return .failure(error)
        }
    }

    /// 處理單一 backgroundSync phase 的並行結果，統一處理 401 / log / Sentry /
    /// CancellationError 過濾。回傳該 phase 的 failure label + UI message；若遇到 401
    /// 則已內部處理 handleUnauthorized + lastBackgroundSyncError 並回傳 nil
    /// 以通知 caller 直接 return。
    private struct SyncPhaseFailure {
        let label: String
        let message: String
    }

    private func processSyncPhase(
        results: [Result<Void, Error>],
        labels: [String],
        container: ModelContainer
    ) async -> [SyncPhaseFailure]? {
        var failures: [SyncPhaseFailure] = []
        for (result, label) in zip(results, labels) {
            guard case .failure(let error) = result else { continue }
            if error is KGError, case KGError.unauthorized = error {
                await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
                lastBackgroundSyncError = L10n.string("登入已過期")
                return nil
            }
            AppLog.kg.warning("backgroundSync \(label) failed: \(error.localizedDescription)")
            if !(error is CancellationError) {
                AppCrashReporting.record(error, context: "kg.sync.\(label)")
            }
            failures.append(SyncPhaseFailure(
                label: label,
                message: SyncFailurePresentation.message(label: label, error: error)
            ))
        }
        return failures
    }

    func backgroundSync(container: ModelContainer) async {
        // 防止併發：快速前景/背景切換可能觸發多個 sync task
        guard claimBackgroundSync() else {
            AppLog.kg.info("backgroundSync skipped: already in progress")
            return
        }
        defer { releaseBackgroundSync() }

        // 先等 logout 排程的本地清理收尾，再動任何 sync 工作。否則快速
        // 「登出→重登」會讓 sync 搶用尚未被清的 sync boundary（incremental
        // 跳過後端全部卡 → 本地空庫但自認最新），且拉回的資料會被 resume 的
        // cleanup 再清一遍 —— 2026-06-09 000287 單字本事故根因。放在入口
        // 單點守住全部四個觸發點（post-login / scenePhase / ⌘R / Settings）。
        await sessionInvalidator.waitForPendingLocalDataCleanup()

        // 每輪開始即重置 error-tracking 欄位：四個 trigger（post-login / scenePhase
        // / ⌘R menu / Settings 手動）共用此全域欄位，但只有 App 層 scenePhase 兩處
        // read-then-clear。claim 鎖已序列化整段（同時間僅一輪執行），於 claim 成功後、
        // offline guard 前清空，可消除跨-trigger 殘留 → 避免 consumer 讀到上一輪 stale
        // 值造成的 analytics 誤判與舊 toast 重彈。失敗時下方會再 set 為本輪正確值。
        lastBackgroundSyncError = nil

        // 離線時跳過整個背景同步，不產生無意義的錯誤日誌
        guard NetworkMonitor.shared.isConnected else {
            AppLog.kg.info("backgroundSync skipped: offline")
            lastBackgroundSyncError = L10n.string("目前沒有網路連線，背景同步已跳過")
            return
        }

        AppCrashReporting.addBreadcrumb(category: "sync", message: "sync.start")
        var failureMessages: [String] = []
        var failureLabels: [String] = []

        // Phase 1: push review states & review events in parallel
        async let pushReviewResult = Self.captureResult { _ = try await self.pushReviewStates(container: container) }
        async let pushEventsResult = Self.captureResult { _ = try await self.pushReviewEvents(container: container) }

        let pushResults = await [pushReviewResult, pushEventsResult]
        if let pushFailures = await processSyncPhase(
            results: pushResults, labels: ["pushReview", "pushReviewEvents"], container: container
        ) {
            failureMessages.append(contentsOf: pushFailures.map(\.message))
            failureLabels.append(contentsOf: pushFailures.map(\.label))
        } else {
            return
        }

        // Phase 2: pull cards & review events in parallel (after push completes)
        async let pullCardsResult = Self.captureResult { try await self.pullCardsToLocal(container: container, progress: nil) }
        async let pullEventsResult = Self.captureResult { try await self.pullReviewEvents(container: container) }

        let pullResults = await [pullCardsResult, pullEventsResult]
        if let pullFailures = await processSyncPhase(
            results: pullResults, labels: ["pull", "pullReviewEvents"], container: container
        ) {
            failureMessages.append(contentsOf: pullFailures.map(\.message))
            failureLabels.append(contentsOf: pullFailures.map(\.label))
        } else {
            return
        }

        // Phase 3: podcast catalog（序執行於 vocab pull 之後）。
        // 把 podcast catalog 同步併入 backgroundSync，使其共用所有既有 resync 觸發
        // （post-login / scenePhase→active / ⌘R menu / Settings 手動同步），補上
        // 「Mac Catalyst 下 .refreshable 下拉不可用、BookshelfView .task 每 view identity
        // 僅跑一次」造成的書架 podcast 區塊一旦未載入便無法復原的缺口。
        // syncAll 內部自我防禦（list fetch 失敗即 skip、空回傳不刪 series），不 throw；
        // 失敗僅記 log，不影響 vocab 結果。token 過期已在前面 vocab pull 的 401 分支提早 return。
        await syncPodcastCatalog(container: container)

        if failureMessages.isEmpty {
            lastBackgroundSyncError = nil
            lastSyncDate = .now
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

    /// Podcast catalog 同步 helper。`PodcastSyncService.syncAll` 為 `@MainActor`，
    /// 需以 main-actor `ModelContext` 呼叫（沿用 `BookshelfView` 既有契約：傳 mainContext，
    /// upsert 在 main actor、@Query 直接取得更新）。整段標 @MainActor 使
    /// `container.mainContext` 存取合法。
    @MainActor
    private func syncPodcastCatalog(container: ModelContainer) async {
        await PodcastSyncService(kgService: self).syncAll(context: container.mainContext)
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
