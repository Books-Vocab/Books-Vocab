//
//  AuthManager.swift
//  Books & Vocab
//
//  Created for Multi-User Apple Sign In
//

import SwiftUI
import Foundation
import GoogleSignIn
import SwiftData
import AuthenticationServices

@MainActor
@Observable
final class AuthManager: AuthManaging, AuthSessionProviding, SessionInvalidating {
    static let shared = AuthManager()

    @ObservationIgnored
    private let verifier: any AuthVerifying

    @ObservationIgnored
    private let localDataCleaner: any LocalDataClearing

    @ObservationIgnored
    private let sessionStore: any AuthSessionStoring

    @ObservationIgnored
    var appleSignInDelegate: AppleSignInDelegate?

    // Stored at app startup so any logout path can clear local data
    var modelContainer: ModelContainer?

    // Status flag published to observers
    var isLoggedIn: Bool = false

    // For UI display of the user id or simple states
    var userId: String?

    var displayName: String?

    var userEmail: String?

    var avatarURL: URL?

    // Secure token memory
    var token: String?

    // Auth error to surface in UI
    var authError: String?

    // True while Apple/Google sign-in + backend verify is in progress
    var isAuthenticating: Bool = false

    // Demo mode — unlocks UI without real auth
    var isDemoMode: Bool = false

    // True while the persisted token could not be read from the keychain (transient failure,
    // e.g. cold boot before first unlock). The session state is *unknown*, not logged-out —
    // `refreshSessionIfNeeded()` re-reads once the device is unlocked. Production observers
    // (e.g. scenePhase → .active) drive that re-read.
    var keychainReadPending: Bool = false

    init(
        verifier: any AuthVerifying = AuthBackendVerifier(),
        localDataCleaner: any LocalDataClearing = LocalDataCleanerService(),
        sessionStore: any AuthSessionStoring = AuthSessionStore()
    ) {
        self.verifier = verifier
        self.localDataCleaner = localDataCleaner
        self.sessionStore = sessionStore
        applyPersistedSession(sessionStore.loadSession())
    }

    /// Maps a `PersistedAuthSession` onto the published auth state.
    ///
    /// The login decision is NOT simply `token != nil`. A transient keychain read failure
    /// (`keychainReadFailed`) yields a nil token for an *already-authenticated* user —
    /// treating that as logged-out silently signs the user out on a cold-boot launch.
    /// So when the read failed we keep the user logged in *if* there is profile evidence of
    /// a prior session (a persisted `userId`), mark the read as pending, and re-read later.
    /// Only a clean read with no token is a genuine logout. The result is deterministic —
    /// it never depends on the prior value of `isLoggedIn`.
    private func applyPersistedSession(_ persisted: PersistedAuthSession) {
        self.userId = persisted.userId
        self.displayName = persisted.displayName
        self.userEmail = persisted.userEmail
        self.avatarURL = persisted.avatarURL
        self.token = persisted.token

        if persisted.keychainReadFailed {
            // Unknown state: don't flip a logged-in user to logged-out. Keep them in only if
            // a prior session left a profile behind; never *fabricate* a login otherwise.
            self.keychainReadPending = true
            self.isLoggedIn = persisted.userId != nil
        } else {
            self.keychainReadPending = false
            self.isLoggedIn = persisted.token != nil
        }
    }

    /// Re-reads the persisted session if a prior read failed transiently. Intended to run
    /// when the app/scene becomes active (device now unlocked), resolving the unknown state:
    /// a recovered token confirms login, a clean "no token" performs the deferred logout.
    /// A no-op when no read was pending.
    func refreshSessionIfNeeded() {
        guard keychainReadPending else { return }
        applyPersistedSession(sessionStore.loadSession())
    }

    func login(userId: String, token: String) {
        let userIdStr = userId.trimmingCharacters(in: .whitespacesAndNewlines)
        let tokenStr = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !userIdStr.isEmpty, !tokenStr.isEmpty else { return }

        // Real login replaces demo mode — clean up demo data
        if isDemoMode, let container = modelContainer {
            DemoDataProvider.removeDemoEntries(from: container)
            isDemoMode = false
        }

        if let existing = self.userId, existing != userIdStr {
            AppLog.auth.info("Account switch detected, clearing sync + notebook state")
            let defaults = UserDefaults.standard
            // 用 KGService.SyncKeys 常數，與 LocalDataCleanerService / sync 路徑單一真相對齊。
            defaults.removeObject(forKey: KGService.SyncKeys.incrementalBoundary)
            defaults.removeObject(forKey: KGService.SyncKeys.payloadVersion)
            // 與 clearLocalData 對齊：漏清 review-event cursor 會讓經 login(customToken:)
            // 的手動帳號切換（SettingsCoordinator）讓 B 沿用 A 的 review pull cursor。
            defaults.removeObject(forKey: KGService.SyncKeys.reviewEventPullBoundary)
            ActiveNotebookStore.shared.clear()
            defaults.removeObject(forKey: NotebookFilter.storageKey)
            AppAnalytics.track(.accountSwitchDetected)
        }

        self.userId = userIdStr
        self.token = tokenStr
        sessionStore.persistProfile(
            userId: userIdStr,
            displayName: displayName,
            userEmail: userEmail,
            avatarURL: avatarURL
        )
        sessionStore.persistToken(tokenStr)
        self.isLoggedIn = true
        PerfLog.auth.mark("auth.state.login")
    }

    /// Manual/debug login via a raw custom token (userId == token), surfaced only in
    /// the DEBUG Settings account section. Mirrors `applyAuthenticatedUser`'s
    /// account-switch contract: when switching away from a prior user it clears that
    /// user's SwiftData (vocab/notebooks/review-records/books) *before* establishing
    /// the new session, so the manual-login path doesn't leave account A's rows
    /// visible under account B. `login(userId:token:)` then handles the UserDefaults
    /// sync-boundary + notebook-state reset. The empty-token guard mirrors
    /// `login(userId:token:)` so a blank token neither switches nor wipes.
    func login(customToken: String) async {
        let userIdStr = customToken.trimmingCharacters(in: .whitespacesAndNewlines)
        if !userIdStr.isEmpty,
           let existing = self.userId,
           existing != userIdStr,
           let container = self.modelContainer {
            AppLog.auth.info("Manual login account switch — clearing previous user's local data")
            await localDataCleaner.clearLocalData(container: container, reason: "manual_login_account_switch")
        }
        login(userId: customToken, token: customToken)
    }

    func logout(modelContainer: ModelContainer? = nil, reason: String = "user_logout") {
        AppAnalytics.track(.logoutPerformed(reason: reason))
        let container = modelContainer ?? self.modelContainer
        Task {
            // Clear session state UP FRONT, before awaiting clearLocalData. The cleanup hops to
            // BackgroundSyncActor — a real suspension that yields the MainActor. Doing the nils
            // + clearSession() after that await (the old order) opened a TOCTOU window: a
            // login() in that window was unconditionally wiped back to nil on resume, kicking
            // the user out right after they signed back in. clearLocalData needs only the
            // container + reason (no userId/token), so front-loading is safe.
            GIDSignIn.sharedInstance.signOut()
            self.userId = nil
            self.token = nil
            self.displayName = nil
            self.userEmail = nil
            self.avatarURL = nil
            self.sessionStore.clearSession()
            self.isLoggedIn = false
            PerfLog.auth.mark("auth.state.logout", "reason=\(reason)")

            if let container {
                await localDataCleaner.clearLocalData(container: container, reason: reason)
            }

            // Stale-guard (mirrors SubscriptionManager+Refresh requestUserId check), second line
            // of defence after the up-front teardown. The teardown left userId == nil; if a
            // login() interleaved during the await, userId is now non-nil — a fresh session we
            // must not touch. Should any post-cleanup teardown ever be added below, it stops
            // here in that race.
            guard self.userId == nil else {
                AppLog.auth.info("logout: session re-established during cleanup; skipping post-cleanup teardown")
                return
            }
        }
    }

    func applyAuthenticatedUser(
        userId: String,
        jwtToken: String,
        displayName: String?,
        email: String?,
        avatarURL: URL?,
        accountSwitchReason: String,
        modelContainer: ModelContainer?
    ) async {
        authError = nil
        if let displayName, !displayName.isEmpty { self.displayName = displayName }
        if let email, !email.isEmpty { self.userEmail = email }
        self.avatarURL = avatarURL
        sessionStore.persistProfile(
            userId: self.userId,
            displayName: self.displayName,
            userEmail: self.userEmail,
            avatarURL: self.avatarURL
        )

        let isAccountSwitch = self.userId != nil && self.userId != userId
        if isAccountSwitch, let container = modelContainer {
            AppLog.auth.info("Account switch — clearing previous user's local data")
            await localDataCleaner.clearLocalData(container: container, reason: accountSwitchReason)
        }
        login(userId: userId, token: jwtToken)
    }

    func enterDemoMode(modelContainer: ModelContainer) {
        isDemoMode = true
        isLoggedIn = true
        displayName = "Demo"
        DemoDataProvider.injectDemoEntries(into: modelContainer)
    }

    func exitDemoMode(modelContainer: ModelContainer) {
        DemoDataProvider.removeDemoEntries(from: modelContainer)
        isDemoMode = false
        // Restore real auth state — `applyPersistedSession` handles a transient keychain
        // read failure (keeps a prior session logged in, marks the read pending).
        applyPersistedSession(sessionStore.loadSession())
    }

    func setAuthError(_ message: String) {
        authError = message
    }

    func verify(provider: String, token: String, email: String?) async throws -> AuthVerificationResult {
        try await verifier.verify(provider: provider, token: token, email: email)
    }
}
