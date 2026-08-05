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
        /// Last successful device sync, persisted so Settings can still answer
        /// "when did this last sync?" after a cold start. Held in memory only,
        /// it read as "never synced" on every launch until the first sync of
        /// that session finished.
        static let lastSyncDate = "kg_last_sync_date"
    }

    /// Persist the last successful sync instant. `nil` clears it (logout /
    /// account switch), so the next account never inherits the previous one's
    /// timestamp.
    static func persistLastSyncDate(_ date: Date?, defaults: UserDefaults = .standard) {
        guard let date else {
            defaults.removeObject(forKey: SyncKeys.lastSyncDate)
            return
        }
        defaults.set(date.timeIntervalSince1970, forKey: SyncKeys.lastSyncDate)
    }

    static func loadPersistedLastSyncDate(defaults: UserDefaults = .standard) -> Date? {
        // `double(forKey:)` returns 0 for a missing key, which would render as
        // 1970 — an absent timestamp must stay absent, not become a wrong one.
        guard defaults.object(forKey: SyncKeys.lastSyncDate) != nil else { return nil }
        let seconds = defaults.double(forKey: SyncKeys.lastSyncDate)
        guard seconds > 0 else { return nil }
        return Date(timeIntervalSince1970: seconds)
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
    var lastSyncDate: Date? = KGService.loadPersistedLastSyncDate()
    var serverCardCount: Int = 0
    var sessionExpiredReason: String?

    /// 最近一次背景同步失敗訊息（UI 可觀測）
    var lastBackgroundSyncError: String?

    /// Guard against concurrent backgroundSync calls (e.g. rapid foreground/background toggling)
    @ObservationIgnored
    private let _backgroundSyncLock = NSLock()
    @ObservationIgnored
    private var _isBackgroundSyncing = false

    /// Serialises review-event pushes across the two entry points that reach
    /// them: `backgroundSync` (behind `claimBackgroundSync`) and
    /// `SyncCoordinator.startSync`, which calls `pushReviewEvents` directly and
    /// so was never covered by that lock. Production logs showed both running at
    /// once (two client ports interleaving PATCHes) and doubling the burst
    /// against a 60-request/minute budget.
    ///
    /// Deliberately its own lock rather than widening `claimBackgroundSync`:
    /// the explicit user-initiated sync must not be silently downgraded because
    /// a background sync holds that claim.
    @ObservationIgnored
    private let _reviewEventPushLock = NSLock()
    @ObservationIgnored
    private var _isPushingReviewEvents = false

    /// Returns `true` when the caller owns the review-event push. A `false`
    /// return means another push is already in flight; with the `pushedAt`
    /// watermark in place that push covers this caller's events too, so
    /// skipping loses nothing.
    func claimReviewEventPush() -> Bool {
        _reviewEventPushLock.lock()
        defer { _reviewEventPushLock.unlock() }
        guard !_isPushingReviewEvents else { return false }
        _isPushingReviewEvents = true
        return true
    }

    func releaseReviewEventPush() {
        _reviewEventPushLock.lock()
        _isPushingReviewEvents = false
        _reviewEventPushLock.unlock()
    }

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
