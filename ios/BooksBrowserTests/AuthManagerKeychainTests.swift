import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

/// Pins `AuthManager`'s handling of a *transient* Keychain read failure.
///
/// Root cause (PR #529 follow-up): on a cold-boot device that has not been unlocked,
/// `loadSession()` returns a `PersistedAuthSession` with `token == nil` even though the
/// token is physically present — the read failed with `errSecInteractionNotAllowed`.
/// `AuthManager.init` then evaluated `isLoggedIn = token != nil` → `false`, silently
/// logging out an already-authenticated user.
///
/// The fix: `loadSession()` now also carries `keychainReadFailed`. When that is true the
/// session state is *unknown*, not logged-out — `AuthManager` keeps the user logged in if
/// there is profile evidence of a prior session, and re-reads when the device unlocks.
@MainActor
struct AuthManagerKeychainTests {

    /// A scripted `AuthSessionStoring` whose `loadSession()` return value the test controls,
    /// including the per-call sequence so a "first read fails, second succeeds" cold-boot
    /// → unlock transition can be reproduced.
    private final class FakeSessionStore: AuthSessionStoring {
        /// FIFO of sessions handed out by successive `loadSession()` calls. The last entry
        /// is reused once exhausted, so a single-element queue yields a stable result.
        var sessionQueue: [PersistedAuthSession]
        private(set) var loadCount = 0
        private(set) var clearCount = 0

        init(_ sessions: [PersistedAuthSession]) {
            precondition(!sessions.isEmpty)
            self.sessionQueue = sessions
        }

        func loadSession() -> PersistedAuthSession {
            loadCount += 1
            if sessionQueue.count > 1 {
                return sessionQueue.removeFirst()
            }
            return sessionQueue[0]
        }
        func persistProfile(userId: String?, displayName: String?, userEmail: String?, avatarURL: URL?) {}
        func persistToken(_ token: String?) {}
        func clearSession() { clearCount += 1 }
    }

    private func session(
        userId: String? = nil,
        token: String? = nil,
        keychainReadFailed: Bool = false
    ) -> PersistedAuthSession {
        PersistedAuthSession(
            userId: userId,
            displayName: nil,
            userEmail: nil,
            avatarURL: nil,
            token: token,
            keychainReadFailed: keychainReadFailed
        )
    }

    private func makeManager(_ store: FakeSessionStore) -> AuthManager {
        AuthManager(
            verifier: NoopVerifier(),
            localDataCleaner: NoopCleaner(),
            sessionStore: store
        )
    }

    private final class NoopVerifier: AuthVerifying {
        func verify(provider: String, token: String, email: String?) async throws -> AuthVerificationResult {
            throw CancellationError()
        }
    }
    private final class NoopCleaner: LocalDataClearing {
        func clearLocalData(container: ModelContainer, reason: String) async {}
    }

    // MARK: - (a) transient read failure must NOT log the user out

    @Test func transient_read_failure_with_prior_profile_keeps_user_logged_in() {
        // Cold-boot: token unreadable, but a persisted userId proves a prior session existed.
        let store = FakeSessionStore([session(userId: "u-1", token: nil, keychainReadFailed: true)])
        let manager = makeManager(store)
        // The user must NOT be shown as logged out — state is unknown, pending re-read.
        #expect(manager.isLoggedIn == true)
        #expect(manager.keychainReadPending == true)
    }

    // MARK: - (b) genuine logged-out state still routes to logout

    @Test func itemNotFound_with_no_profile_is_a_normal_logged_out_launch() {
        // No token, no profile, no read failure — a legitimately signed-out user.
        let store = FakeSessionStore([session(userId: nil, token: nil, keychainReadFailed: false)])
        let manager = makeManager(store)
        #expect(manager.isLoggedIn == false)
        #expect(manager.keychainReadPending == false)
    }

    @Test func valid_token_is_logged_in_with_no_pending_reread() {
        let store = FakeSessionStore([session(userId: "u-1", token: "jwt.alive", keychainReadFailed: false)])
        let manager = makeManager(store)
        #expect(manager.isLoggedIn == true)
        #expect(manager.keychainReadPending == false)
    }

    /// Defensive: a read failure with *no* profile evidence (never logged in on this device)
    /// must not fabricate a logged-in state — there is nothing to restore.
    @Test func transient_read_failure_without_profile_does_not_fake_login() {
        let store = FakeSessionStore([session(userId: nil, token: nil, keychainReadFailed: true)])
        let manager = makeManager(store)
        #expect(manager.isLoggedIn == false)
        // Still pending: a re-read after unlock is harmless and may yet surface a token.
        #expect(manager.keychainReadPending == true)
    }

    // MARK: - (c) re-read after unlock resolves the unknown state

    @Test func refresh_after_unlock_restores_token_and_clears_pending() {
        // First load fails (cold boot); second load succeeds (device now unlocked).
        let store = FakeSessionStore([
            session(userId: "u-1", token: nil, keychainReadFailed: true),
            session(userId: "u-1", token: "jwt.recovered", keychainReadFailed: false)
        ])
        let manager = makeManager(store)
        #expect(manager.keychainReadPending == true)
        #expect(manager.token == nil)

        manager.refreshSessionIfNeeded()

        #expect(manager.keychainReadPending == false)
        #expect(manager.isLoggedIn == true)
        #expect(manager.token == "jwt.recovered")
    }

    @Test func refresh_after_unlock_revealing_no_token_logs_user_out() {
        // The read recovers, but there genuinely is no token — the user is logged out.
        let store = FakeSessionStore([
            session(userId: "u-1", token: nil, keychainReadFailed: true),
            session(userId: nil, token: nil, keychainReadFailed: false)
        ])
        let manager = makeManager(store)
        #expect(manager.isLoggedIn == true)  // unknown → optimistically logged in

        manager.refreshSessionIfNeeded()

        #expect(manager.keychainReadPending == false)
        #expect(manager.isLoggedIn == false)
        #expect(manager.token == nil)
    }

    @Test func refresh_is_a_noop_when_no_read_was_pending() {
        let store = FakeSessionStore([session(userId: "u-1", token: "jwt.alive", keychainReadFailed: false)])
        let manager = makeManager(store)
        let loadsAfterInit = store.loadCount

        manager.refreshSessionIfNeeded()

        // No pending read → no second loadSession call, state unchanged.
        #expect(store.loadCount == loadsAfterInit)
        #expect(manager.isLoggedIn == true)
        #expect(manager.token == "jwt.alive")
    }

    @Test func refresh_keeps_pending_when_keychain_still_locked() {
        // Device still locked on the next active transition — stay pending, retry later.
        let store = FakeSessionStore([
            session(userId: "u-1", token: nil, keychainReadFailed: true),
            session(userId: "u-1", token: nil, keychainReadFailed: true)
        ])
        let manager = makeManager(store)
        manager.refreshSessionIfNeeded()
        #expect(manager.keychainReadPending == true)
        #expect(manager.isLoggedIn == true)
    }
}
