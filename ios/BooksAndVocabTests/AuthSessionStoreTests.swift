import Foundation
import Testing
@testable import BooksAndVocab

/// Pins `AuthSessionStore` — the persistence seam that decides, on every launch, whether a
/// cached auth session is restorable. A wrong load (stale token, dropped profile field)
/// silently logs the user out or restores half a session.
///
/// The store is fully injectable: `UserDefaults` (a per-test suite-named instance, never
/// `.standard`) and `KeychainHelping` (an in-memory fake below). No production keychain is
/// touched. Keychain `save` overwrite-on-duplicate semantics are reproduced by the fake so
/// the persist→re-persist path is exercised honestly.
struct AuthSessionStoreTests {

    /// In-memory `KeychainHelping`: a dictionary keyed by `service|account`, mirroring the
    /// real helper's add-or-update behaviour (a second save overwrites, returns success).
    private final class FakeKeychain: KeychainHelping {
        private(set) var storage: [String: Data] = [:]
        private(set) var deleteCount = 0
        /// When set, `save`/`delete` return this status instead of success and skip the
        /// mutation — used to exercise the keychain-write-failure reporting path.
        var forcedFailureStatus: OSStatus?
        /// When set, `readWithStatus` returns this status with nil data — used to exercise the
        /// keychain-*read*-failure reporting path (cold-boot, pre-first-unlock device). Kept
        /// separate from `forcedFailureStatus` so a test can fail a read without also failing
        /// the `save` that seeds it.
        var forcedReadStatus: OSStatus?

        private func key(_ service: String, _ account: String) -> String { "\(service)|\(account)" }

        func save(_ data: Data, service: String, account: String) -> OSStatus {
            if let forced = forcedFailureStatus { return forced }
            storage[key(service, account)] = data
            return errSecSuccess
        }
        func readWithStatus(service: String, account: String) -> (data: Data?, status: OSStatus) {
            if let forced = forcedReadStatus { return (nil, forced) }
            if let data = storage[key(service, account)] {
                return (data, errSecSuccess)
            }
            // Mirror the real helper: an absent item yields `errSecItemNotFound`, the
            // benign "logged out" status — *not* a generic failure.
            return (nil, errSecItemNotFound)
        }
        @discardableResult
        func delete(service: String, account: String) -> OSStatus {
            if let forced = forcedFailureStatus { return forced }
            deleteCount += 1
            storage.removeValue(forKey: key(service, account))
            return errSecSuccess
        }
    }

    /// Fresh, isolated `UserDefaults` + fake keychain + store for one test.
    private func makeStore() -> (AuthSessionStore, UserDefaults, FakeKeychain) {
        let suite = "AuthSessionStoreTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        let keychain = FakeKeychain()
        return (AuthSessionStore(defaults: defaults, keychain: keychain), defaults, keychain)
    }

    // MARK: - Empty state

    @Test func loadSession_returns_all_nil_on_fresh_store() {
        let (store, _, _) = makeStore()
        let session = store.loadSession()
        #expect(session.userId == nil)
        #expect(session.displayName == nil)
        #expect(session.userEmail == nil)
        #expect(session.avatarURL == nil)
        #expect(session.token == nil)
    }

    // MARK: - Profile round-trip

    @Test func persistProfile_then_load_restores_every_field() {
        let (store, _, _) = makeStore()
        let avatar = URL(string: "https://cdn.example.com/a.png")!
        store.persistProfile(userId: "u-1", displayName: "Max",
                             userEmail: "max@example.com", avatarURL: avatar)
        let session = store.loadSession()
        #expect(session.userId == "u-1")
        #expect(session.displayName == "Max")
        #expect(session.userEmail == "max@example.com")
        #expect(session.avatarURL == avatar)
        // Profile and token are independent stores — profile-only persist leaves token nil.
        #expect(session.token == nil)
    }

    @Test func persistProfile_with_nil_fields_loads_back_as_nil() {
        let (store, _, _) = makeStore()
        store.persistProfile(userId: nil, displayName: nil, userEmail: nil, avatarURL: nil)
        let session = store.loadSession()
        #expect(session.userId == nil)
        #expect(session.displayName == nil)
        #expect(session.avatarURL == nil)
    }

    @Test func persistProfile_overwrites_previous_values() {
        let (store, _, _) = makeStore()
        store.persistProfile(userId: "old", displayName: "Old Name",
                             userEmail: "old@x.com", avatarURL: nil)
        store.persistProfile(userId: "new", displayName: "New Name",
                             userEmail: "new@x.com", avatarURL: nil)
        let session = store.loadSession()
        #expect(session.userId == "new")
        #expect(session.displayName == "New Name")
        #expect(session.userEmail == "new@x.com")
    }

    @Test func avatarURL_round_trips_through_string_serialization() {
        // avatarURL is stored as `absoluteString` and re-parsed via `URL(string:)`.
        // A query-bearing URL confirms the string round-trip is lossless.
        let (store, _, _) = makeStore()
        let url = URL(string: "https://h.io/img?size=64&v=2")!
        store.persistProfile(userId: nil, displayName: nil, userEmail: nil, avatarURL: url)
        #expect(store.loadSession().avatarURL == url)
    }

    // MARK: - Token round-trip

    @Test func persistToken_then_load_restores_token() {
        let (store, _, keychain) = makeStore()
        store.persistToken("jwt-abc.def.ghi")
        #expect(store.loadSession().token == "jwt-abc.def.ghi")
        #expect(keychain.storage.count == 1)
    }

    @Test func persistToken_nil_deletes_keychain_entry() {
        // The documented branch: persisting a nil token must purge the keychain item,
        // not store an empty value — otherwise a logged-out user keeps a phantom token.
        let (store, _, keychain) = makeStore()
        store.persistToken("live-token")
        #expect(store.loadSession().token == "live-token")

        store.persistToken(nil)
        #expect(store.loadSession().token == nil)
        #expect(keychain.storage.isEmpty)
        #expect(keychain.deleteCount == 1)
    }

    @Test func persistToken_overwrites_previous_token() {
        let (store, _, _) = makeStore()
        store.persistToken("token-v1")
        store.persistToken("token-v2")
        #expect(store.loadSession().token == "token-v2")
    }

    @Test func persistToken_empty_string_is_stored_verbatim() {
        // An empty string is non-nil and `"".data(using:.utf8)` is non-nil, so the guard
        // passes and an empty token is saved (not treated as a logout). Pins that the
        // nil-vs-empty distinction is real.
        let (store, _, keychain) = makeStore()
        store.persistToken("")
        #expect(store.loadSession().token == "")
        #expect(keychain.deleteCount == 0)
    }

    // MARK: - clearSession

    @Test func clearSession_wipes_profile_and_token() {
        let (store, _, keychain) = makeStore()
        store.persistProfile(userId: "u-1", displayName: "Max",
                             userEmail: "max@x.com",
                             avatarURL: URL(string: "https://x.io/a.png"))
        store.persistToken("token")

        store.clearSession()
        let session = store.loadSession()
        #expect(session.userId == nil)
        #expect(session.displayName == nil)
        #expect(session.userEmail == nil)
        #expect(session.avatarURL == nil)
        #expect(session.token == nil)
        #expect(keychain.storage.isEmpty)
    }

    @Test func clearSession_on_empty_store_is_idempotent() {
        let (store, _, _) = makeStore()
        store.clearSession()
        store.clearSession()
        #expect(store.loadSession().userId == nil)
        #expect(store.loadSession().token == nil)
    }

    // MARK: - Keychain failure reporting

    /// The bug fix's core seam: a keychain write that fails must not throw or corrupt the
    /// store's contract. `persistToken` still returns; the (unwritten) token simply reads
    /// back nil — matching the real-world symptom (session lost) but now diagnosable.
    @Test func persistToken_tolerates_keychain_save_failure() {
        let (store, _, keychain) = makeStore()
        keychain.forcedFailureStatus = errSecNotAvailable  // device locked, pre-first-unlock
        store.persistToken("token-that-cannot-be-written")
        #expect(store.loadSession().token == nil)
        #expect(keychain.storage.isEmpty)
    }

    @Test func clearSession_tolerates_keychain_delete_failure() {
        let (store, _, keychain) = makeStore()
        keychain.forcedFailureStatus = errSecNotAvailable
        store.clearSession()  // must not throw
        #expect(store.loadSession().userId == nil)
    }

    // MARK: - Keychain *read* failure reporting (PR #529 follow-up)

    /// Root cause: `loadSession` previously read the token via a `-> Data?` keychain call that
    /// discarded the `OSStatus`. A cold-boot device that has not been unlocked returns
    /// `errSecInteractionNotAllowed` — indistinguishable, under the old API, from "no token".
    /// The app would then route a still-logged-in user to the login screen with no trace.
    /// This pins that such a read failure is now surfaced via `reportKeychainFailure`.
    @Test func loadSession_reports_keychain_read_failure() {
        let (store, _, keychain) = makeStore()
        var reported: [KeychainError] = []
        store.keychainFailureObserver = { reported.append($0) }

        keychain.forcedReadStatus = errSecInteractionNotAllowed  // cold-boot, pre-unlock
        let session = store.loadSession()

        // The failure must be reported (not swallowed) and attributed to the read op...
        #expect(reported.count == 1)
        #expect(reported.first?.status == errSecInteractionNotAllowed)
        #expect(reported.first?.operation == "read")
        // ...and the token reads back nil — the load still succeeds, it does not throw.
        #expect(session.token == nil)
    }

    /// The critical non-firing case: `errSecItemNotFound` means "no token stored", i.e. the
    /// user is legitimately logged out. It must NOT be reported as a keychain failure —
    /// doing so would flag a crash event on every cold launch of a signed-out app.
    @Test func loadSession_does_not_report_when_token_absent() {
        let (store, _, keychain) = makeStore()
        var reported: [KeychainError] = []
        store.keychainFailureObserver = { reported.append($0) }

        keychain.forcedReadStatus = errSecItemNotFound  // legitimate logged-out state
        let session = store.loadSession()

        #expect(reported.isEmpty)
        #expect(session.token == nil)
    }

    /// A fresh store (no token ever persisted) drives the fake's natural `errSecItemNotFound`
    /// path — confirming the benign-not-found branch holds without a forced status, so an
    /// ordinary signed-out launch never reports a keychain failure.
    @Test func loadSession_on_fresh_store_reports_no_keychain_failure() {
        let (store, _, _) = makeStore()
        var reported: [KeychainError] = []
        store.keychainFailureObserver = { reported.append($0) }

        _ = store.loadSession()
        #expect(reported.isEmpty)
    }

    /// A successfully persisted token reads back without any failure report — the success
    /// path is untouched by the status-surfacing change.
    @Test func loadSession_with_valid_token_reports_no_keychain_failure() {
        let (store, _, _) = makeStore()
        var reported: [KeychainError] = []
        store.keychainFailureObserver = { reported.append($0) }

        store.persistToken("jwt.alive")
        let session = store.loadSession()
        #expect(session.token == "jwt.alive")
        #expect(reported.isEmpty)
    }

    // MARK: - keychainReadFailed flag (transient-failure vs logged-out distinction)

    /// A transient read failure (cold-boot, pre-first-unlock) must set `keychainReadFailed`
    /// so `AuthManager` can tell "could not read the token" apart from "no token stored".
    @Test func loadSession_sets_keychainReadFailed_on_transient_read_failure() {
        let (store, _, keychain) = makeStore()
        keychain.forcedReadStatus = errSecInteractionNotAllowed
        let session = store.loadSession()
        #expect(session.keychainReadFailed == true)
        #expect(session.token == nil)
    }

    /// `errSecItemNotFound` is the legitimate logged-out state, NOT a transient failure —
    /// `keychainReadFailed` must stay false so the normal logout path is preserved.
    @Test func loadSession_keychainReadFailed_false_when_token_absent() {
        let (store, _, keychain) = makeStore()
        keychain.forcedReadStatus = errSecItemNotFound
        let session = store.loadSession()
        #expect(session.keychainReadFailed == false)
        #expect(session.token == nil)
    }

    /// A successful read leaves `keychainReadFailed` false.
    @Test func loadSession_keychainReadFailed_false_on_successful_read() {
        let (store, _, _) = makeStore()
        store.persistToken("jwt.alive")
        let session = store.loadSession()
        #expect(session.keychainReadFailed == false)
        #expect(session.token == "jwt.alive")
    }

    /// A fresh store reads back as logged-out, not transiently failed.
    @Test func loadSession_keychainReadFailed_false_on_fresh_store() {
        let (store, _, _) = makeStore()
        #expect(store.loadSession().keychainReadFailed == false)
    }

    // MARK: - KeychainStatus seam (pure function)

    @Test func keychainStatus_success_is_not_a_failure() {
        #expect(KeychainStatus.isFailure(errSecSuccess) == false)
    }

    @Test func keychainStatus_itemNotFound_is_not_a_failure() {
        // Deleting an absent item is the expected idempotent outcome, not an error —
        // reporting it would spam crash reporting on every logged-out clearSession.
        #expect(KeychainStatus.isFailure(errSecItemNotFound) == false)
    }

    @Test func keychainStatus_locked_device_status_is_a_failure() {
        // errSecNotAvailable / errSecInteractionNotAllowed are the cold-boot, pre-unlock
        // failures the fix exists to surface.
        #expect(KeychainStatus.isFailure(errSecNotAvailable))
        #expect(KeychainStatus.isFailure(errSecInteractionNotAllowed))
    }

    @Test func keychainStatus_error_carries_status_and_operation() {
        let err = KeychainStatus.error(errSecNotAvailable, operation: "save")
        #expect(err.status == errSecNotAvailable)
        #expect(err.operation == "save")
        // diagnosticMessage is PII-free: status code + OS message only.
        #expect(err.diagnosticMessage.contains("\(errSecNotAvailable)"))
    }

    @Test func clearSession_then_repersist_yields_clean_session() {
        // After a logout, a fresh login must restore exactly the new values with no
        // bleed-through from the cleared session.
        let (store, _, _) = makeStore()
        store.persistProfile(userId: "old", displayName: "Old",
                             userEmail: "old@x.com", avatarURL: nil)
        store.persistToken("old-token")
        store.clearSession()

        store.persistProfile(userId: "fresh", displayName: "Fresh",
                             userEmail: "fresh@x.com", avatarURL: nil)
        store.persistToken("fresh-token")
        let session = store.loadSession()
        #expect(session.userId == "fresh")
        #expect(session.token == "fresh-token")
    }
}

// NOTE: `AuthBackendVerifier` is intentionally NOT unit-tested here. Its `verify(...)` is one
// monolithic method with no injection seam — `NetworkMonitor.shared`, `KGService.getServerURL()`
// and `sharedURLSession` are all hard-wired globals. Exercising it would require either a live
// network or process-wide URLProtocol stubbing, neither of which yields a deterministic pure-
// function test. The decode/credential-extraction logic that *could* be tested is inlined into
// the network call and not reachable in isolation. Left uncovered honestly rather than faked.
