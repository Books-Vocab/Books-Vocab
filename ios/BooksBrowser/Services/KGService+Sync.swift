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

        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/review")
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        request.httpBody = try JSONSerialization.data(withJSONObject: ["entries": payload])

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to push review state (HTTP \(httpResponse.statusCode))")
        }

        struct PushResponse: Decodable {
            let updated: Int
            let skipped: Int
        }
        let result = try JSONDecoder().decode(PushResponse.self, from: data)
        AppLog.kg.info("pushReviewStates: updated=\(result.updated), skipped=\(result.skipped)")
        return (result.updated, result.skipped)
    }

    // MARK: - Offline KG Sync logic

    @discardableResult
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)? = nil) async throws -> Bool {
        let token = try await currentAuthToken()
        progress?(L10n.string("從遠端下載知識庫..."), 0, 0)

        let defaults = UserDefaults.standard
        let storedPayloadVersion = defaults.integer(forKey: SyncKeys.payloadVersion)
        if storedPayloadVersion < SyncKeys.currentPayloadVersion {
            defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
            progress?(L10n.string("升級卡片資料格式，重新同步全部卡片..."), 0, 0)
        }

        guard var urlComponents = URLComponents(url: baseURL.appendingPathComponent("api/vocab"), resolvingAgainstBaseURL: false) else {
            throw KGError.serverError("Invalid URL")
        }

        let lastSyncMillis = defaults.double(forKey: SyncKeys.incrementalBoundary)
        let isIncremental = lastSyncMillis > 0

        if isIncremental {
            let lastSyncDate = Date(timeIntervalSince1970: lastSyncMillis)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let dateString = formatter.string(from: lastSyncDate)
            urlComponents.queryItems = [URLQueryItem(name: "since", value: dateString)]
            AppLog.kg.info("Performing incremental sync since: \(dateString)")
        } else {
            AppLog.kg.info("Performing full sync")
        }

        guard let url = urlComponents.url else {
            throw KGError.serverError("Invalid URL")
        }

        // Bug A fix: 記錄邊界在發起請求前，避免 pull 期間新增的卡片被跳過
        let pullBoundary = Date().timeIntervalSince1970

        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to fetch cards, HTTP \(httpResponse.statusCode)")
        }

        progress?(L10n.string("解析資料..."), 0, 0)
        let fetchedCards: [KGCard]
        do {
            fetchedCards = try JSONDecoder().decode([KGCard].self, from: data)
        } catch {
            AppLog.kg.error("Failed to decode KG cards: \(error.localizedDescription)")
            throw KGError.serverError("Parse error: \(error.localizedDescription)")
        }

        // Let the new Actor handle SwiftData operations safely off the main thread.
        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.pullCardsToLocal(
            fetchedCards: fetchedCards,
            isIncremental: isIncremental,
            progress: { detail, current, total in
                progress?(detail, current, total)
            }
        )

        // 使用 pull 開始前的時間戳作為邊界，確保不遺漏 pull 期間的變更
        defaults.set(pullBoundary, forKey: SyncKeys.incrementalBoundary)
        defaults.set(SyncKeys.currentPayloadVersion, forKey: SyncKeys.payloadVersion)

        // Back-fill pronunciations for entries that are missing them (non-blocking)
        Task.detached(priority: .utility) {
            try? await actor.backfillPronunciations()
        }

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

        UserDefaults.standard.removeObject(forKey: SyncKeys.incrementalBoundary)
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
        } catch {
            AppLog.kg.warning("backgroundSync pushReview failed: \(error.localizedDescription)")
            failures.append("pushReview")
        }
        do {
            _ = try await pushDailyStats(container: container)
        } catch {
            AppLog.kg.warning("backgroundSync pushDailyStats failed: \(error.localizedDescription)")
            failures.append("pushDailyStats")
        }
        do {
            try await pullCardsToLocal(container: container, progress: nil)
        } catch {
            AppLog.kg.warning("backgroundSync pull failed: \(error.localizedDescription)")
            failures.append("pull")
        }
        do {
            try await pullDailyStats(container: container)
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
