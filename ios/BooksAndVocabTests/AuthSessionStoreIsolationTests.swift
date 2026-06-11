import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// Pins the isolated-auth-session persistence contract（2026-06-11 sim 殘留 401 事故）。
///
/// `-isolatedAuthSession` 先前只擋 `loadSession`（啟動清 + 回空 session），
/// `persistProfile` / `persistToken` 仍無條件落真 UserDefaults + keychain ——
/// UI-test fixture 經真 `AuthManager.login` 寫入的假 session（ui-auth-user）
/// 殘留給後續 unit-test 的 host app（正常模式啟動、無啞端點防線），
/// 拿假 token 對生產發請求 → 401×3，並把生產 401 誤歸因到真實用戶裝置。
///
/// 契約：isolated 模式下 session store 全程 in-memory（真 store 零寫入），
/// 建立時清掉先前殘留；正常模式行為不變。
@MainActor
struct AuthSessionStoreIsolationTests {

    private static let isolatedArgs = ["BooksAndVocab", "-ui-testing", "-isolatedAuthSession"]
    private static let normalArgs = ["BooksAndVocab"]

    /// 記錄所有寫入的 keychain spy —— 斷言「真 keychain 零寫入」用。
    private final class SpyKeychain: KeychainHelping {
        private(set) var saved: [String: Data] = [:]
        private(set) var deleteCount = 0

        func save(_ data: Data, service: String, account: String) -> OSStatus {
            saved["\(service)/\(account)"] = data
            return errSecSuccess
        }
        func readWithStatus(service: String, account: String) -> (data: Data?, status: OSStatus) {
            if let data = saved["\(service)/\(account)"] { return (data, errSecSuccess) }
            return (nil, errSecItemNotFound)
        }
        @discardableResult
        func delete(service: String, account: String) -> OSStatus {
            deleteCount += 1
            return saved.removeValue(forKey: "\(service)/\(account)") == nil
                ? errSecItemNotFound : errSecSuccess
        }
    }

    private func makeDefaults() -> UserDefaults {
        let suite = "isolation-tests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return defaults
    }

    @Test func isolatedStorePersistsNothingToRealStores() {
        let defaults = makeDefaults()
        let keychain = SpyKeychain()
        let store = AuthSessionStore.makeSessionStore(
            arguments: Self.isolatedArgs, defaults: defaults, keychain: keychain
        )

        store.persistProfile(
            userId: "ui-auth-user",
            displayName: "UI Auth Tester",
            userEmail: "ui-auth-tester@example.com",
            avatarURL: nil
        )
        store.persistToken("ui-auth-user-token")

        #expect(defaults.string(forKey: "KGUserId") == nil,
                "isolated persistProfile 不得落真 UserDefaults")
        #expect(keychain.saved.isEmpty,
                "isolated persistToken 不得落真 keychain")
    }

    @Test func isolatedStoreRoundTripsInMemory() {
        let store = AuthSessionStore.makeSessionStore(
            arguments: Self.isolatedArgs, defaults: makeDefaults(), keychain: SpyKeychain()
        )

        store.persistProfile(
            userId: "ui-auth-user", displayName: "UI Auth Tester",
            userEmail: "ui-auth-tester@example.com", avatarURL: nil
        )
        store.persistToken("ui-auth-user-token")
        let session = store.loadSession()

        #expect(session.userId == "ui-auth-user")
        #expect(session.token == "ui-auth-user-token")
        #expect(session.keychainReadFailed == false)

        store.clearSession()
        #expect(store.loadSession().userId == nil)
        #expect(store.loadSession().token == nil)
    }

    @Test func isolatedStorePurgesRealStoreResidueOnCreation() {
        let defaults = makeDefaults()
        let keychain = SpyKeychain()
        // 預埋先前 run 的殘留。
        defaults.set("stale-user", forKey: "KGUserId")
        _ = keychain.save(Data("stale-token".utf8), service: "kg-auth", account: "kgToken")

        _ = AuthSessionStore.makeSessionStore(
            arguments: Self.isolatedArgs, defaults: defaults, keychain: keychain
        )

        #expect(defaults.string(forKey: "KGUserId") == nil,
                "isolated store 建立時必須清掉真 store 殘留")
        #expect(keychain.saved.isEmpty,
                "isolated store 建立時必須清掉真 keychain 殘留")
    }

    @Test func normalStorePersistsToRealStores() {
        let defaults = makeDefaults()
        let keychain = SpyKeychain()
        let store = AuthSessionStore.makeSessionStore(
            arguments: Self.normalArgs, defaults: defaults, keychain: keychain
        )

        store.persistProfile(userId: "real-user", displayName: nil, userEmail: nil, avatarURL: nil)
        store.persistToken("real-token")

        #expect(defaults.string(forKey: "KGUserId") == "real-user",
                "正常模式 persist 行為不得改變")
        #expect(keychain.saved["kg-auth/kgToken"] == Data("real-token".utf8))
    }

    /// Seed guard：unit-test host app（無 -ui-testing / -isolatedAuthSession 引數）
    /// 下 seedAuth("signedIn") 必須拒絕 —— 否則假 session 經真 AuthManager.login
    /// 落盤，殘留打生產。
    @Test func signedInSeedRefusesOutsideIsolatedSession() throws {
        // 行為斷言對「seed 前後不變」：shared 的絕對值取決於 sim 容器歷史殘留，
        // 不可斷言。unit-test process 無 -ui-testing 引數 → guard 必須拒絕 seed。
        let userIdBefore = AuthManager.shared.userId
        let tokenBefore = AuthManager.shared.token
        let loggedInBefore = AuthManager.shared.isLoggedIn
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: Notebook.self, configurations: config)

        UITestFixtureSeed.seedAuth("signedIn", into: container)

        #expect(AuthManager.shared.userId == userIdBefore,
                "unit-test 環境（非 isolated session）seedAuth(signedIn) 不得改動真 AuthManager")
        #expect(AuthManager.shared.token == tokenBefore)
        #expect(AuthManager.shared.isLoggedIn == loggedInBefore)
    }
}
