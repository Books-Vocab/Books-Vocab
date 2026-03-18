//
//  KGService+Stats.swift
//  BooksBrowser
//

import Foundation
import SwiftData

// MARK: - Daily Review Stats Sync

extension KGService {

    func pushDailyStats(container: ModelContainer) async throws -> Int {
        let actor = BackgroundSyncActor(modelContainer: container)
        let payload = try await actor.buildDailyStatsPushPayload()
        guard !payload.isEmpty else { return 0 }

        struct PushResponse: Decodable { let upserted: Int }
        let result = try await authenticatedDecode(
            PushResponse.self,
            path: "api/vocab/daily-stats",
            method: "PATCH",
            body: try JSONSerialization.data(withJSONObject: ["entries": payload])
        )
        AppLog.kg.info("pushDailyStats: upserted=\(result.upserted)")
        return result.upserted
    }

    func pullDailyStats(container: ModelContainer) async throws {
        struct StatsResponse: Decodable {
            struct Entry: Decodable {
                let day_key: String
                let total: Int
                let remembered: Int
                let forgot: Int
            }
            let entries: [Entry]
        }

        let decoded = try await authenticatedDecode(
            StatsResponse.self,
            path: "api/vocab/daily-stats"
        )
        guard !decoded.entries.isEmpty else { return }

        let remoteStats: [[String: Any]] = decoded.entries.map {
            ["day_key": $0.day_key, "total": $0.total, "remembered": $0.remembered, "forgot": $0.forgot]
        }
        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.mergeDailyStats(remoteStats)
        AppLog.kg.info("pullDailyStats: merged \(decoded.entries.count) remote entries")
    }
}
