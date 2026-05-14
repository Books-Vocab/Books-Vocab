//
//  KGService+Sync.swift
//  BooksBrowser
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
        try await actor.pullCardsToLocal(
            fetchedCards: fetchedCards,
            isIncremental: isIncremental,
            progress: { detail, current, total in
                progress?(detail, current, total)
            },
            notebookId: notebookId ?? "default"
        )

        defaults.set(pullBoundary, forKey: SyncKeys.incrementalBoundary)
        defaults.set(SyncKeys.currentPayloadVersion, forKey: SyncKeys.payloadVersion)

        return httpResponse.value(forHTTPHeaderField: "X-Pipeline-Pending") == "true"
    }

    func clearLocalData(container: ModelContainer, reason: String = "unspecified") async {
        let actor = BackgroundSyncActor(modelContainer: container)
        AppLog.kg.info("clearLocalData requested. reason=\(reason)")
        do {
            try await actor.clearVocabularyData(reason: reason)
        } catch {
            AppLog.kg.error("clearVocabularyData failed: \(error.localizedDescription)")
            AppCrashReporting.record(error, context: "kg.local.clear")
        }

        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
        defaults.removeObject(forKey: SyncKeys.payloadVersion)
        defaults.removeObject(forKey: "activeNotebookId")
        defaults.removeObject(forKey: NotebookFilter.storageKey)
        lastSyncDate = nil
        serverCardCount = 0
    }

    // MARK: - Background Sync (輕量：push review + pull)

    func backgroundSync(container: ModelContainer) async {
        // 防止併發：快速前景/背景切換可能觸發多個 sync task
        guard claimBackgroundSync() else {
            AppLog.kg.info("backgroundSync skipped: already in progress")
            return
        }
        defer { releaseBackgroundSync() }

        // 離線時跳過整個背景同步，不產生無意義的錯誤日誌
        guard NetworkMonitor.shared.isConnected else {
            AppLog.kg.info("backgroundSync skipped: offline")
            lastBackgroundSyncError = L10n.string("目前沒有網路連線，背景同步已跳過")
            return
        }

        AppCrashReporting.addBreadcrumb(category: "sync", message: "sync.start")
        var failures: [String] = []

        // Phase 1: push review states & daily stats in parallel
        async let pushReviewResult: Result<Void, Error> = {
            do {
                _ = try await self.pushReviewStates(container: container)
                return .success(())
            } catch {
                return .failure(error)
            }
        }()
        async let pushStatsResult: Result<Void, Error> = {
            do {
                _ = try await self.pushDailyStats(container: container)
                return .success(())
            } catch {
                return .failure(error)
            }
        }()

        let pushResults = await [pushReviewResult, pushStatsResult]
        let pushLabels = ["pushReview", "pushDailyStats"]

        for (result, label) in zip(pushResults, pushLabels) {
            if case .failure(let error) = result {
                if error is KGError, case KGError.unauthorized = error {
                    await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
                    lastBackgroundSyncError = "Session expired"
                    return
                }
                AppLog.kg.warning("backgroundSync \(label) failed: \(error.localizedDescription)")
                if !(error is CancellationError) {
                    AppCrashReporting.record(error, context: "kg.sync.\(label)")
                }
                failures.append(label)
            }
        }

        // Phase 2: pull cards & daily stats in parallel (after push completes)
        async let pullCardsResult: Result<Void, Error> = {
            do {
                try await self.pullCardsToLocal(container: container, progress: nil)
                return .success(())
            } catch {
                return .failure(error)
            }
        }()
        async let pullStatsResult: Result<Void, Error> = {
            do {
                try await self.pullDailyStats(container: container)
                return .success(())
            } catch {
                return .failure(error)
            }
        }()

        let pullResults = await [pullCardsResult, pullStatsResult]
        let pullLabels = ["pull", "pullDailyStats"]

        for (result, label) in zip(pullResults, pullLabels) {
            if case .failure(let error) = result {
                if error is KGError, case KGError.unauthorized = error {
                    await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
                    lastBackgroundSyncError = "Session expired"
                    return
                }
                AppLog.kg.warning("backgroundSync \(label) failed: \(error.localizedDescription)")
                if !(error is CancellationError) {
                    AppCrashReporting.record(error, context: "kg.sync.\(label)")
                }
                failures.append(label)
            }
        }

        if failures.isEmpty {
            lastBackgroundSyncError = nil
            lastSyncDate = .now
            AppCrashReporting.addBreadcrumb(category: "sync", message: "sync.end.success")
        } else {
            lastBackgroundSyncError = L10n.format("背景同步部分失敗：%@", failures.joined(separator: ", "))
            AppCrashReporting.addBreadcrumb(
                category: "sync",
                message: "sync.end.partial",
                level: .warning,
                data: ["failures": failures]
            )
        }
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
            _ = try await pushDailyStats(container: container)
        } catch {
            AppLog.kg.warning("pushReviewQuietly pushDailyStats failed: \(error.localizedDescription)")
        }
    }
}
