//
//  KGService.swift
//  BooksBrowser
//
//  Knowledge Graph API client — communicates with the KG FastAPI server.
//

import Foundation
import SwiftData
import os

/// Manages communication with the Knowledge Graph API server
@Observable
final class KGService: KGServing, LocalDataClearing {
    enum SyncKeys {
        static let incrementalBoundary = "kg_last_incremental_sync"
        static let payloadVersion = "kg_review_payload_version"
        static let currentPayloadVersion = 1
    }

    @ObservationIgnored
    private let authSession: any AuthSessionProviding

    @ObservationIgnored
    private let sessionInvalidator: any SessionInvalidating

    @ObservationIgnored
    let userConfigClient: any KGUserConfigRemoteHandling

    var serverURL: String {
        get { Self.getServerURL() }
        set { Self.setServerURL(newValue) }
    }

    var isConnected: Bool = false
    var lastSyncDate: Date?
    var serverCardCount: Int = 0
    var sessionExpiredReason: String?

    /// 最近一次背景同步失敗訊息（UI 可觀測）
    var lastBackgroundSyncError: String?

    /// Guard against concurrent backgroundSync calls (e.g. rapid foreground/background toggling)
    @ObservationIgnored
    private let _backgroundSyncLock = NSLock()
    @ObservationIgnored
    private var _isBackgroundSyncing = false

    /// Thread-safe check-and-set for background sync guard.
    /// Returns `true` if sync was successfully claimed (caller should proceed).
    func claimBackgroundSync() -> Bool {
        _backgroundSyncLock.lock()
        defer { _backgroundSyncLock.unlock() }
        guard !_isBackgroundSyncing else { return false }
        _isBackgroundSyncing = true
        return true
    }

    func releaseBackgroundSync() {
        _backgroundSyncLock.lock()
        defer { _backgroundSyncLock.unlock() }
        _isBackgroundSyncing = false
    }

    var baseURL: URL {
        var clean = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if !clean.hasPrefix("http://") && !clean.hasPrefix("https://") {
            clean = "http://" + clean
        }
        if let url = URL(string: clean) ?? URL(string: Self.deployedServerURL) {
            return url
        }
        // Should be unreachable — `deployedServerURL` is a compile-time literal.
        // Fail-soft: log and return guaranteed fallback rather than crash.
        AppLog.kg.error("Invalid deployedServerURL constant: \(Self.deployedServerURL) — using fallback")
        return Self.fallbackURL
    }

    init(
        authSession: any AuthSessionProviding = MainActor.assumeIsolated({ AuthManager.shared }),
        sessionInvalidator: any SessionInvalidating = MainActor.assumeIsolated({ AuthManager.shared }),
        userConfigClient: any KGUserConfigRemoteHandling = KGUserConfigClient()
    ) {
        self.authSession = authSession
        self.sessionInvalidator = sessionInvalidator
        self.userConfigClient = userConfigClient
    }

    // MARK: - Auth Helper

    func currentAuthToken() async throws -> String {
        guard NetworkMonitor.shared.isConnected else {
            throw KGError.offline
        }
        guard let token = await authSession.token else {
            throw KGError.unauthorized
        }
        if JWTExpiry.isExpired(token) {
            AppLog.kg.warning("Token expired (pre-check), triggering session invalidation")
            sessionExpiredReason = L10n.string("您的登入已過期，請重新登入")
            await sessionInvalidator.logout(modelContainer: nil, reason: "token_expired_precheck")
            throw KGError.unauthorized
        }
        return token
    }

    // MARK: - Session Invalidation (internal for extensions)

    func handleUnauthorized(modelContainer: ModelContainer?, reason: String) async {
        sessionExpiredReason = L10n.string("您的登入已過期，請重新登入")
        await sessionInvalidator.logout(modelContainer: modelContainer, reason: reason)
    }

    // MARK: - Health Check

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

    // MARK: - Quota

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
        }
    }

}

