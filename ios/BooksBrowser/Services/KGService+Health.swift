//
//  KGService+Health.swift
//  Books & Vocab
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
            let snapshot = health.snapshot
            isConnected = snapshot.isConnected
            serverCardCount = snapshot.serverCardCount
            // 刻意不更新 lastSyncDate：health 是探活，拿到的 lastModified 是「後端資料
            // 最後寫入時間」，與「裝置最後同步時間」語意不同。lastSyncDate 只由
            // backgroundSync 成功時設定（見 KGService+Sync.swift），避免純 pull 後時間倒退。
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
