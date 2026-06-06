//
//  KGService+ReviewEvents.swift
//  BooksBrowser
//

import Foundation
import SwiftData

struct KGReviewEventPayload: Codable, Sendable, Equatable {
    let event_id: String
    let card_id: String?
    let word_snapshot: String
    let notebook_id: String
    let feedback: Int
    let reviewed_at: String
    let created_at: String
}

// MARK: - Review Event Sync

extension KGService {
    private static let reviewEventPushBatchSize = 1000

    func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int) {
        let actor = BackgroundSyncActor(modelContainer: container)
        let payload = try await actor.buildReviewEventsPushPayload()
        guard !payload.isEmpty else { return (0, 0) }

        struct PushResponse: Decodable {
            let inserted: Int
            let skipped: Int
        }

        var totalInserted = 0
        var totalSkipped = 0
        for batchStart in stride(from: 0, to: payload.count, by: Self.reviewEventPushBatchSize) {
            let batchEnd = min(batchStart + Self.reviewEventPushBatchSize, payload.count)
            let batch = Array(payload[batchStart..<batchEnd])
            let result = try await authenticatedDecode(
                PushResponse.self,
                path: "api/vocab/review-events",
                method: "PATCH",
                body: try JSONEncoder().encode(["entries": batch])
            )
            totalInserted += result.inserted
            totalSkipped += result.skipped
        }
        AppLog.kg.info("pushReviewEvents: inserted=\(totalInserted), skipped=\(totalSkipped), batches=\((payload.count + Self.reviewEventPushBatchSize - 1) / Self.reviewEventPushBatchSize)")
        return (totalInserted, totalSkipped)
    }

    func pullReviewEvents(container: ModelContainer) async throws {
        struct EventsResponse: Decodable {
            let entries: [KGReviewEventPayload]
            let cursor: String?
        }

        let defaults = UserDefaults.standard
        let since = defaults.string(forKey: SyncKeys.reviewEventPullBoundary)
        let queryItems = since.map { [URLQueryItem(name: "since", value: $0)] }

        let decoded = try await authenticatedDecode(
            EventsResponse.self,
            path: "api/vocab/review-events",
            queryItems: queryItems
        )
        guard !decoded.entries.isEmpty else { return }

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.mergeReviewEvents(decoded.entries)
        // Advance the watermark by the server-assigned ingestion cursor, not by
        // max(reviewed_at): the cursor is monotonic in ingestion order, so a later
        // pull cannot skip an event whose reviewed_at lies before this boundary.
        if let cursor = decoded.cursor {
            defaults.set(cursor, forKey: SyncKeys.reviewEventPullBoundary)
        } else {
            // Contract violation: a non-empty batch must carry a cursor. Surface it
            // instead of silently re-merging the same batch every sync.
            AppLog.kg.error("pullReviewEvents: non-empty batch returned nil cursor; watermark not advanced")
        }
        AppLog.kg.info("pullReviewEvents: merged \(decoded.entries.count) remote events")
    }
}

// MARK: - Watermark self-heal migration

extension KGService {
    /// review-event pull watermark 是否為「乾淨、可安全回送」的格式。
    ///
    /// 乾淨 cursor 一律來自後端 `_format_timestamp`（tz-aware ISO8601，帶 offset、
    /// 可選小數秒），故以嚴格 `ISO8601DateFormatter` 能否解析為準。舊版 app 曾把
    /// 非嚴格字串（naive / 空格分隔 / 純日期）寫入此 key，後端 review-event pull
    /// 對其回 400 → watermark 永不前進 → 每輪背景同步 partial fail → 每次回前台彈
    /// toast（死鎖）。
    static func isCleanReviewEventBoundary(_ raw: String) -> Bool {
        AppDateFormatters.parseISO8601(raw) != nil
    }

    /// 一次性自癒 migration：清除無法回送的舊 watermark，下次 pull 走全量
    /// （冪等、無損：review events 以 `event_id` 去重 merge）。打破「壞 watermark →
    /// 後端 400 → 永不前進」死鎖。在 app 啟動早期（任何背景同步之前）呼叫。
    static func migrateReviewEventBoundaryIfNeeded(defaults: UserDefaults = .standard) {
        guard let raw = defaults.string(forKey: SyncKeys.reviewEventPullBoundary) else { return }
        guard !isCleanReviewEventBoundary(raw) else { return }
        defaults.removeObject(forKey: SyncKeys.reviewEventPullBoundary)
        AppLog.kg.info("Cleared stale review-event boundary (not tz-aware ISO8601): \(raw)")
    }
}
