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

        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/daily-stats")
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
            throw KGError.serverError("Failed to push daily stats (HTTP \(httpResponse.statusCode))")
        }

        struct PushResponse: Decodable { let upserted: Int }
        let result = try JSONDecoder().decode(PushResponse.self, from: data)
        AppLog.kg.info("pushDailyStats: upserted=\(result.upserted)")
        return result.upserted
    }

    func pullDailyStats(container: ModelContainer) async throws {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/daily-stats")
        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to pull daily stats (HTTP \(httpResponse.statusCode))")
        }

        struct StatsResponse: Decodable {
            struct Entry: Decodable {
                let day_key: String
                let total: Int
                let remembered: Int
                let forgot: Int
            }
            let entries: [Entry]
        }

        let decoded = try JSONDecoder().decode(StatsResponse.self, from: data)
        guard !decoded.entries.isEmpty else { return }

        let remoteStats: [[String: Any]] = decoded.entries.map {
            ["day_key": $0.day_key, "total": $0.total, "remembered": $0.remembered, "forgot": $0.forgot]
        }

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.mergeDailyStats(remoteStats)
        AppLog.kg.info("pullDailyStats: merged \(decoded.entries.count) remote entries")
    }
}
