import Foundation
import Security

struct PersistedAuthSession {
    let userId: String?
    let displayName: String?
    let userEmail: String?
    let avatarURL: URL?
    let token: String?
    /// True when the token *could not be read* (transient keychain failure, e.g.
    /// `errSecInteractionNotAllowed` on a cold-boot, pre-first-unlock device) — as opposed
    /// to `errSecItemNotFound`, the legitimate "no token stored / logged out" outcome.
    ///
    /// A nil `token` is therefore ambiguous on its own: it can mean either "logged out" or
    /// "read failed". This flag disambiguates them. When true the caller MUST treat the
    /// session as *unknown* (not logged-out) and re-read once the device is unlocked —
    /// otherwise an already-authenticated user is silently signed out (PR #529 follow-up).
    let keychainReadFailed: Bool

    init(
        userId: String?,
        displayName: String?,
        userEmail: String?,
        avatarURL: URL?,
        token: String?,
        keychainReadFailed: Bool = false
    ) {
        self.userId = userId
        self.displayName = displayName
        self.userEmail = userEmail
        self.avatarURL = avatarURL
        self.token = token
        self.keychainReadFailed = keychainReadFailed
    }
}

protocol AuthSessionStoring: AnyObject {
    func loadSession() -> PersistedAuthSession
    func persistProfile(userId: String?, displayName: String?, userEmail: String?, avatarURL: URL?)
    func persistToken(_ token: String?)
    func clearSession()
}

final class AuthSessionStore: AuthSessionStoring {
    private enum Keys {
        static let userId = "KGUserId"
        static let displayName = "KGDisplayName"
        static let userEmail = "KGUserEmail"
        static let avatarURL = "KGAvatarURL"
        static let tokenService = "kg-auth"
        static let tokenAccount = "kgToken"
    }

    private let defaults: UserDefaults
    private let keychain: KeychainHelping

    /// Test-only observation seam. When set, every reportable keychain failure (the exact set
    /// `reportKeychainFailure` forwards to crash reporting) is also handed to this closure.
    /// Production leaves it nil — `AppCrashReporting.record` is a static, un-injectable sink,
    /// so this is the only way a test can assert "the read failure was surfaced, not swallowed".
    var keychainFailureObserver: ((KeychainError) -> Void)?

    init(
        defaults: UserDefaults = .standard,
        keychain: KeychainHelping = KeychainHelper.standard
    ) {
        self.defaults = defaults
        self.keychain = keychain
    }

    /// Composition root：依啟動引數決定 session store 實作。
    /// `-isolatedAuthSession`（須同時 `-ui-testing`）→ ephemeral store：
    /// 建立時清掉真 store 殘留，之後 load/persist 全程 in-memory、真
    /// UserDefaults + keychain 零寫入。先前 isolated 只擋 loadSession、
    /// persist 仍落真盤 —— UI-test fixture 經 AuthManager.login 寫入的假
    /// session 殘留給後續 unit-test host app 打生產（2026-06-11 401 事故）。
    static func makeSessionStore(
        arguments: [String] = ProcessInfo.processInfo.arguments,
        defaults: UserDefaults = .standard,
        keychain: KeychainHelping = KeychainHelper.standard
    ) -> any AuthSessionStoring {
        let persistent = AuthSessionStore(defaults: defaults, keychain: keychain)
        if AppRuntimeOptions.shouldUseIsolatedAuthSession(arguments: arguments) {
            return EphemeralAuthSessionStore(purging: persistent)
        }
        return persistent
    }

    func loadSession() -> PersistedAuthSession {
        let userId = defaults.string(forKey: Keys.userId)
        let displayName = defaults.string(forKey: Keys.displayName)
        let userEmail = defaults.string(forKey: Keys.userEmail)
        let avatarURL = defaults.string(forKey: Keys.avatarURL).flatMap(URL.init(string:))
        // Read the token *with* its OSStatus so a transient keychain failure (e.g.
        // `errSecInteractionNotAllowed` on a cold-boot device that hasn't been unlocked)
        // is reported rather than silently mistaken for "user is logged out".
        let tokenRead = keychain.readWithStatus(service: Keys.tokenService, account: Keys.tokenAccount)
        reportKeychainFailure(tokenRead.status, operation: "read")
        let token = tokenRead.data.flatMap { String(data: $0, encoding: .utf8) }
        // A reportable status (not success, not the benign `errSecItemNotFound`) means the
        // read *failed* rather than "no token" — surface it so a nil token is not mistaken
        // for a logged-out user. `KeychainStatus.isFailure` is the single source of truth.
        let keychainReadFailed = KeychainStatus.isFailure(tokenRead.status)

        return PersistedAuthSession(
            userId: userId,
            displayName: displayName,
            userEmail: userEmail,
            avatarURL: avatarURL,
            token: token,
            keychainReadFailed: keychainReadFailed
        )
    }

    func persistProfile(userId: String?, displayName: String?, userEmail: String?, avatarURL: URL?) {
        defaults.set(userId, forKey: Keys.userId)
        defaults.set(displayName, forKey: Keys.displayName)
        defaults.set(userEmail, forKey: Keys.userEmail)
        defaults.set(avatarURL?.absoluteString, forKey: Keys.avatarURL)
    }

    func persistToken(_ token: String?) {
        guard let token, let data = token.data(using: .utf8) else {
            let status = keychain.delete(service: Keys.tokenService, account: Keys.tokenAccount)
            reportKeychainFailure(status, operation: "delete(persistToken)")
            return
        }
        let status = keychain.save(data, service: Keys.tokenService, account: Keys.tokenAccount)
        reportKeychainFailure(status, operation: "save")
    }

    func clearSession() {
        defaults.removeObject(forKey: Keys.userId)
        defaults.removeObject(forKey: Keys.displayName)
        defaults.removeObject(forKey: Keys.userEmail)
        defaults.removeObject(forKey: Keys.avatarURL)
        let status = keychain.delete(service: Keys.tokenService, account: Keys.tokenAccount)
        reportKeychainFailure(status, operation: "delete(clearSession)")
    }

    /// Surfaces a keychain `OSStatus` that the prior implementation silently discarded.
    /// On `AccessibleAfterFirstUnlock`-locked devices (cold boot, no unlock) or under a
    /// keychain quota anomaly a `save`/`delete` write — or a `read` (`errSecInteractionNotAllowed`)
    /// — can fail, dropping the session on the next launch with no trace. We log at error level
    /// and forward to crash reporting so the failure is diagnosable. The success path is
    /// unchanged. `errSecItemNotFound` is *not* a failure: for `read` it is the legitimate
    /// "no token stored / user is logged out" outcome, for `delete` the idempotent purge.
    private func reportKeychainFailure(_ status: OSStatus, operation: String) {
        guard KeychainStatus.isFailure(status) else { return }
        let error = KeychainStatus.error(status, operation: operation)
        AppLog.auth.error("Keychain \(operation, privacy: .public) failed: \(error.diagnosticMessage, privacy: .public)")
        AppCrashReporting.record(error, context: "auth.keychain.\(operation)")
        keychainFailureObserver?(error)
    }
}

/// In-memory session store for `-isolatedAuthSession` UI-test runs。
/// 真 store 只在建立時被清一次（殘留淨空），之後所有讀寫都留在記憶體 ——
/// process 結束即蒸發，下一個（任意模式的）host app 啟動讀到的是干淨真 store。
final class EphemeralAuthSessionStore: AuthSessionStoring {
    private var session = PersistedAuthSession(
        userId: nil, displayName: nil, userEmail: nil, avatarURL: nil, token: nil
    )

    init(purging persistent: AuthSessionStore) {
        persistent.clearSession()
    }

    func loadSession() -> PersistedAuthSession { session }

    func persistProfile(userId: String?, displayName: String?, userEmail: String?, avatarURL: URL?) {
        session = PersistedAuthSession(
            userId: userId,
            displayName: displayName,
            userEmail: userEmail,
            avatarURL: avatarURL,
            token: session.token
        )
    }

    func persistToken(_ token: String?) {
        session = PersistedAuthSession(
            userId: session.userId,
            displayName: session.displayName,
            userEmail: session.userEmail,
            avatarURL: session.avatarURL,
            token: token
        )
    }

    func clearSession() {
        session = PersistedAuthSession(
            userId: nil, displayName: nil, userEmail: nil, avatarURL: nil, token: nil
        )
    }
}

/// Pure classification + wrapping of keychain `OSStatus` results. Extracted as a seam so the
/// "is this an OSStatus worth reporting?" decision is unit-testable without touching Security.
enum KeychainStatus {
    /// A keychain op is a *reportable* failure when it is neither success nor the benign
    /// `errSecItemNotFound`. For `delete`, `errSecItemNotFound` means "nothing to purge" —
    /// the expected idempotent outcome. For `read`, it means "no item stored", i.e. the
    /// user is simply logged out — a legitimate state, not a fault. Reporting it would spam
    /// crash reporting on every cold launch of a signed-out app.
    static func isFailure(_ status: OSStatus) -> Bool {
        status != errSecSuccess && status != errSecItemNotFound
    }

    /// Wraps an `OSStatus` as an `Error` so it can flow into `AppCrashReporting.record`,
    /// which only accepts `Error`. Carries the OS-provided message when available.
    static func error(_ status: OSStatus, operation: String) -> KeychainError {
        KeychainError(status: status, operation: operation)
    }
}

/// `Error` wrapper around a failing keychain `OSStatus`.
struct KeychainError: Error {
    let status: OSStatus
    let operation: String

    /// Human-readable, PII-free description (the OS message describes the status code only).
    var diagnosticMessage: String {
        let osMessage = SecCopyErrorMessageString(status, nil) as String?
        return "OSStatus \(status) — \(osMessage ?? "unknown")"
    }
}

protocol KeychainHelping: AnyObject {
    func save(_ data: Data, service: String, account: String) -> OSStatus
    /// Reads a keychain item, returning both the value and the raw `OSStatus`.
    ///
    /// The status MUST be surfaced to the caller: the prior `-> Data?` signature collapsed
    /// "no item stored" (`errSecItemNotFound`) and "read failed" (`errSecInteractionNotAllowed`
    /// on a cold-boot, pre-first-unlock device) into the same `nil`. That ambiguity made a
    /// transient keychain failure indistinguishable from a logged-out user — the same silent
    /// session drop PR #529 set out to eliminate, but on the read path.
    ///
    /// On success `data` is the stored value; on `errSecItemNotFound` `data` is nil and the
    /// status is benign; on any other status `data` is nil and the caller should report it.
    func readWithStatus(service: String, account: String) -> (data: Data?, status: OSStatus)
    @discardableResult
    func delete(service: String, account: String) -> OSStatus
}

final class KeychainHelper: KeychainHelping {
    static let standard = KeychainHelper()
    private init() {}

    func save(_ data: Data, service: String, account: String) -> OSStatus {
        let query = [
            kSecValueData: data,
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ] as CFDictionary

        var status = SecItemAdd(query, nil)

        if status == errSecDuplicateItem {
            let queryToUpdate = [
                kSecAttrService: service,
                kSecAttrAccount: account,
                kSecClass: kSecClassGenericPassword,
            ] as CFDictionary

            let attributesToUpdate = [kSecValueData: data] as CFDictionary
            status = SecItemUpdate(queryToUpdate, attributesToUpdate)
        }
        return status
    }

    func readWithStatus(service: String, account: String) -> (data: Data?, status: OSStatus) {
        let query = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne
        ] as CFDictionary

        var dataTypeRef: AnyObject?
        let status = SecItemCopyMatching(query, &dataTypeRef)

        // Return the status verbatim — the caller decides whether it is benign
        // (`errSecItemNotFound`) or a reportable failure. Data is only meaningful on success.
        if status == errSecSuccess {
            return (dataTypeRef as? Data, status)
        }
        return (nil, status)
    }

    @discardableResult
    func delete(service: String, account: String) -> OSStatus {
        let query = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account
        ] as CFDictionary

        return SecItemDelete(query)
    }
}
