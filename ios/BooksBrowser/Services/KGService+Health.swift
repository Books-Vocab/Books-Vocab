//
//  KGService+Health.swift
//  BooksBrowser
//
//  Health check + quota polling.
//

import Foundation

extension KGService {
    func healthCheck() async {
        guard NetworkMonitor.shared.isConnected else {
            isConnected = false
            return
        }
        guard await authSession.isLoggedIn else {
            isConnected = false
            return
        }
        do {
            let (data, httpResponse) = try await authenticatedRequest(path: "api/health")

            if httpResponse.statusCode != 200 {
                isConnected = false
                return
            }

            let health = try JSONDecoder().decode(KGHealthResponse.self, from: data)
            isConnected = health.status == "ok"
            serverCardCount = health.cards

            if let lastModStr = health.lastModified {
                lastSyncDate = AppDateFormatters.iso8601.date(from: lastModStr)
            }
        } catch KGError.unauthorized {
            AppLog.kg.error("Health check failed: 401 Unauthorized")
            AppCrashReporting.record(KGError.unauthorized, context: "kg.health.unauthorized")
            await handleUnauthorized(modelContainer: nil, reason: "healthcheck_401")
            isConnected = false
        } catch {
            isConnected = false
            AppLog.kg.error("Health check failed: \(error.localizedDescription)")
            // healthcheck runs on a timer — only surface unexpected (non-network/cancel) failures
            if !(error is CancellationError),
               !(error is URLError) {
                AppCrashReporting.record(error, context: "kg.health.unexpected")
            }
        }
    }

    func fetchQuota() async {
        guard NetworkMonitor.shared.isConnected, await authSession.isLoggedIn else { return }
        do {
            let (data, httpResponse) = try await authenticatedRequest(path: "api/user/quota")
            guard httpResponse.statusCode == 200 else { return }
            struct QuotaPayload: Decodable { let fraction: Double; let reset_seconds: Int }
            let payload = try JSONDecoder().decode(QuotaPayload.self, from: data)
            await MainActor.run { QuotaStore.shared.update(fraction: payload.fraction, resetSeconds: payload.reset_seconds) }
        } catch {
            AppLog.kg.warning("fetchQuota failed: \(error.localizedDescription)")
            // fetchQuota runs on a timer — only surface unexpected (non-network/cancel)
            // failures so quota response schema drift doesn't fail silently.
            if !(error is CancellationError),
               !(error is URLError) {
                AppCrashReporting.record(error, context: "kg.quota.decode")
            }
        }
    }
}
