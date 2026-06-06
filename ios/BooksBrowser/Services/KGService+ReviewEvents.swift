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

    func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int) {
        let actor = BackgroundSyncActor(modelContainer: container)
        let payload = try await actor.buildReviewEventsPushPayload()
        guard !payload.isEmpty else { return (0, 0) }

        struct PushResponse: Decodable {
            let inserted: Int
            let skipped: Int
        }
        let result = try await authenticatedDecode(
            PushResponse.self,
            path: "api/vocab/review-events",
            method: "PATCH",
            body: try JSONEncoder().encode(["entries": payload])
        )
        AppLog.kg.info("pushReviewEvents: inserted=\(result.inserted), skipped=\(result.skipped)")
        return (result.inserted, result.skipped)
    }

    func pullReviewEvents(container: ModelContainer) async throws {
        struct EventsResponse: Decodable {
            let entries: [KGReviewEventPayload]
        }

        let decoded = try await authenticatedDecode(
            EventsResponse.self,
            path: "api/vocab/review-events"
        )
        guard !decoded.entries.isEmpty else { return }

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.mergeReviewEvents(decoded.entries)
        AppLog.kg.info("pullReviewEvents: merged \(decoded.entries.count) remote events")
    }
}
