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

        let lastSyncMillis = defaults.double(forKey: SyncKeys.incrementalBoundary)
        let isIncremental = lastSyncMillis > 0

        var queryItems: [URLQueryItem] = []
        if let notebookId {
            queryItems.append(URLQueryItem(name: "notebook_id", value: notebookId))
        }
        if isIncremental {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let dateString = formatter.string(from: Date(timeIntervalSince1970: lastSyncMillis))
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
        // 離線時跳過整個背景同步，不產生無意義的錯誤日誌
        guard NetworkMonitor.shared.isConnected else {
            AppLog.kg.info("backgroundSync skipped: offline")
            lastBackgroundSyncError = L10n.string("目前沒有網路連線，背景同步已跳過")
            return
        }

        var failures: [String] = []

        do {
            _ = try await pushReviewStates(container: container)
        } catch KGError.unauthorized {
            await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
            lastBackgroundSyncError = "Session expired"
            return
        } catch {
            AppLog.kg.warning("backgroundSync pushReview failed: \(error.localizedDescription)")
            failures.append("pushReview")
        }
        do {
            _ = try await pushDailyStats(container: container)
        } catch KGError.unauthorized {
            await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
            lastBackgroundSyncError = "Session expired"
            return
        } catch {
            AppLog.kg.warning("backgroundSync pushDailyStats failed: \(error.localizedDescription)")
            failures.append("pushDailyStats")
        }
        do {
            try await pullCardsToLocal(container: container, progress: nil)
        } catch KGError.unauthorized {
            await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
            lastBackgroundSyncError = "Session expired"
            return
        } catch {
            AppLog.kg.warning("backgroundSync pull failed: \(error.localizedDescription)")
            failures.append("pull")
        }
        do {
            try await pullDailyStats(container: container)
        } catch KGError.unauthorized {
            await handleUnauthorized(modelContainer: container, reason: "backgroundSync_401")
            lastBackgroundSyncError = "Session expired"
            return
        } catch {
            AppLog.kg.warning("backgroundSync pullDailyStats failed: \(error.localizedDescription)")
            failures.append("pullDailyStats")
        }

        if failures.isEmpty {
            lastBackgroundSyncError = nil
        } else {
            lastBackgroundSyncError = L10n.format("背景同步部分失敗：%@", failures.joined(separator: ", "))
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
