import Foundation
import Testing
@testable import BooksBrowser

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

        private func key(_ service: String, _ account: String) -> String { "\(service)|\(account)" }

        func save(_ data: Data, service: String, account: String) -> OSStatus {
            storage[key(service, account)] = data
            return errSecSuccess
        }
        func read(service: String, account: String) -> Data? {
            storage[key(service, account)]
        }
        func delete(service: String, account: String) {
            deleteCount += 1
            storage.removeValue(forKey: key(service, account))
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
