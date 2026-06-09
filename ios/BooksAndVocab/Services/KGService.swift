//
//  KGService.swift
//  Books & Vocab
//
//  Knowledge Graph API client — communicates with the KG FastAPI server.
//

import Foundation
import SwiftData

/// Manages communication with the Knowledge Graph API server
@Observable
final class KGService: KGServing, LocalDataClearing {
    enum SyncKeys {
        static let incrementalBoundary = "kg_last_incremental_sync"
        static let reviewEventPullBoundary = "kg_review_events_since"
        static let payloadVersion = "kg_review_payload_version"
        static let currentPayloadVersion = 1
    }

    @ObservationIgnored
    let authSession: any AuthSessionProviding

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

}
