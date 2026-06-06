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
        if let latest = decoded.entries.map(\.reviewed_at).max() {
            defaults.set(latest, forKey: SyncKeys.reviewEventPullBoundary)
        }
        AppLog.kg.info("pullReviewEvents: merged \(decoded.entries.count) remote events")
    }
}
