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

    // internal：KGService+Sync extension（backgroundSync 入口 gate）需要存取。
    @ObservationIgnored
    let sessionInvalidator: any SessionInvalidating

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

    // MARK: - Pull serialization

    /// Serialization chain for `pullCardsToLocal`.
    ///
    /// Production logs showed the same pull firing repeatedly within seconds —
    /// twice with an *identical* `?since=` cursor, proving two pulls read the
    /// same incremental boundary before either wrote it back. Five call sites
    /// reach this pull (view `.task`, pull-to-refresh, the sync sheet's pipeline
    /// poll, `backgroundSync`, the retry banner) and only `backgroundSync` had a
    /// guard, so they raced each other into duplicate server work and duplicate
    /// merges of the same payload.
    ///
    /// **Serialize, don't coalesce.** Making late callers share the earlier
    /// call's response would be cheaper but wrong: several callers need data
    /// *newer than their own action*. The sync sheet pulls right after uploading
    /// words and reads `X-Pipeline-Pending` off that response to decide whether
    /// to keep waiting for AI content — handing it a response fetched before the
    /// upload would answer "nothing pending" and silently skip the wait. Chaining
    /// instead gives every caller its own request, issued after the previous
    /// pull persisted its cursor, so no two requests carry the same `?since=`.
    ///
    /// The chain is global rather than per-notebook because the cursor it
    /// protects (`SyncKeys.incrementalBoundary`) is a single global key.
    @ObservationIgnored
    private let _pullLock = NSLock()
    /// Tail of the chain: the most recently enqueued pull. A new pull awaits it
    /// before starting, then becomes the tail itself.
    @ObservationIgnored
    private var _pullChainTail: Task<KGPullOutcome, Error>?
    @ObservationIgnored
    private var _pullChainSeq: UInt64 = 0
    @ObservationIgnored
    private var _pullChainTailID: UInt64 = 0

    /// Enqueue a pull behind any pull already in flight.
    ///
    /// `makeTask` receives the predecessor to await (`nil` when the chain is
    /// idle) and this pull's id for retirement. Both the read of the old tail and
    /// the write of the new one happen under one lock, so two callers arriving
    /// together are ordered rather than parallel. `makeTask` only constructs a
    /// `Task` — no suspension — so the lock is held for a few instructions.
    func enqueuePull(
        makeTask: (_ predecessor: Task<KGPullOutcome, Error>?, _ id: UInt64) -> Task<KGPullOutcome, Error>
    ) -> Task<KGPullOutcome, Error> {
        _pullLock.lock()
        defer { _pullLock.unlock() }
        _pullChainSeq &+= 1
        let id = _pullChainSeq
        let task = makeTask(_pullChainTail, id)
        _pullChainTail = task
        _pullChainTailID = id
        return task
    }

    /// Retire a finished pull. Keyed by id so a late finisher never clears a
    /// successor that has already taken over as the tail.
    func finishPull(id: UInt64) {
        _pullLock.lock()
        defer { _pullLock.unlock() }
        if _pullChainTailID == id { _pullChainTail = nil }
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
