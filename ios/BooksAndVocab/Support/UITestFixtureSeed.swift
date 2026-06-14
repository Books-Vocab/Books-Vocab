#if os(iOS)
import Foundation
import SwiftData

/// Bridges the existing fixture system into the live SwiftData container for UI tests.
/// Triggered by launch arguments when `-ui-testing` is active.
@MainActor
enum UITestFixtureSeed {
    /// Parse `-seedFixture:<domain>:<id>` arguments and inject matching fixtures.
    static func injectIfNeeded(into container: ModelContainer, arguments: [String]) {
        guard AppRuntimeOptions.isUITesting(arguments: arguments) else { return }

        // 資料安全防線（2026-06-10 事故）：fixture 會 wipe+seed VocabularyEntry。
        // 在真機上對真實 on-disk store 動手 = 清掉使用者整個本地單字庫，
        // 故只允許全 in-memory 容器（bootstrap 在 -ui-testing 下必須提供）。
        // !isEmpty：空配置容器 allSatisfy 恆真（fail-open），雖經查無實際
        // 產生路徑，仍以廉價保險封死。
        guard !container.configurations.isEmpty,
              container.configurations.allSatisfy(\.isStoredInMemoryOnly) else {
            AppLog.app.error("UITestFixtureSeed: refused — container has persistent store(s); fixtures may only seed the ephemeral UI-testing container")
            return
        }

        applyPreferencesFromWorld()

        for arg in arguments {
            guard arg.hasPrefix("-seedFixture:") else { continue }
            let remainder = arg.dropFirst("-seedFixture:".count)
            let parts = remainder.split(separator: ":", maxSplits: 1).map(String.init)
            guard parts.count == 2 else {
                failFixtureSeed("Malformed UI-test fixture argument: \(arg)")
            }
            let domain = parts[0]
            let id = parts[1]

            switch domain {
            case "bookshelf":
                seedBookshelf(id, into: container)
            case "podcast":
                seedPodcast(id, into: container)
            case "todayReview":
                seedTodayReview(id, into: container)
            case "auth":
                seedAuth(id, into: container)
            case "settings":
                seedSettings(id, into: container)
            case "shell":
                seedShell(id, into: container)
            case "search":
                seedSearch(id, into: container)
            case "reader":
                seedReader(id, into: container)
            case "notebook":
                seedNotebook(id, into: container)
            case "entitlements":
                guard id == "pro" || id == "free" else {
                    failFixtureSeed("Unknown entitlements fixture ID: \(id)")
                }
                break
            default:
                failFixtureSeed("Unknown UI-test fixture domain: \(domain)")
            }
        }
    }

    static func failFixtureSeed(_ message: String) -> Never {
        AppLog.app.error("\(message)")
        preconditionFailure(message)
    }

    @MainActor
    private static func applyPreferencesFromWorld() {
        let document = FixtureDatasetStore.requireDocument()
        guard !document.preferences.isEmpty else { return }
        #if targetEnvironment(simulator)
        document.preferences.apply()
        #else
        preconditionFailure("UI World preferences are simulator-only; refusing to overwrite real UserDefaults/iCloud KVS on device")
        #endif
    }

    /// 非容器寫入面的 auth 防線：`AuthManager.login` 經 AuthSessionStore 直寫
    /// 真實 UserDefaults + Keychain。真機上跑 signedIn 類 fixture 會用假 token
    /// 蓋掉使用者真 session——下次正常啟動 401 → 自動 logout + clearLocalData，
    /// 2026-06-10 事故經另一儲存平面重演。與 settings/reader fixture 同款
    /// simulator gate；fixture 一律經此 helper，不得直呼 login。
    @MainActor
    static func seedSignedInLoginFromWorld() {
        #if targetEnvironment(simulator)
        let seed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        guard seed.isLoggedIn else {
            preconditionFailure("auth.signedIn fixture requires auth.signedIn.isLoggedIn = true")
        }
        let userId = seed.userId ?? ""
        guard !userId.isEmpty else {
            preconditionFailure("auth.signedIn fixture requires non-empty userId")
        }
        let auth = AuthManager.shared
        auth.displayName = seed.displayName ?? ""
        auth.userEmail = seed.email
        switch seed.keychainTokenState {
        case .available:
            let token = seed.token ?? ""
            guard !token.isEmpty else {
                preconditionFailure("auth.signedIn keychainTokenState=available requires non-empty token")
            }
            auth.login(userId: userId, token: token)
        case .readFailed:
            auth.applyUITestPersistedSession(PersistedAuthSession(
                userId: userId,
                displayName: seed.displayName,
                userEmail: seed.email,
                avatarURL: nil,
                token: nil,
                keychainReadFailed: true
            ))
        case .absent:
            preconditionFailure("auth.signedIn cannot declare keychainTokenState=absent")
        }
        #else
        AppLog.app.error("UITestFixtureSeed: refused fixture login on physical device — would overwrite the real Keychain session")
        preconditionFailure("auth.signedIn fixture is simulator-only")
        #endif
    }
}
#endif
