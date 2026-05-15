import Foundation
import Security

struct PersistedAuthSession {
    let userId: String?
    let displayName: String?
    let userEmail: String?
    let avatarURL: URL?
    let token: String?
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

    init(
        defaults: UserDefaults = .standard,
        keychain: KeychainHelping = KeychainHelper.standard
    ) {
        self.defaults = defaults
        self.keychain = keychain
    }

    func loadSession() -> PersistedAuthSession {
        let userId = defaults.string(forKey: Keys.userId)
        let displayName = defaults.string(forKey: Keys.displayName)
        let userEmail = defaults.string(forKey: Keys.userEmail)
        let avatarURL = defaults.string(forKey: Keys.avatarURL).flatMap(URL.init(string:))
        let token = keychain
            .read(service: Keys.tokenService, account: Keys.tokenAccount)
            .flatMap { String(data: $0, encoding: .utf8) }

        return PersistedAuthSession(
            userId: userId,
            displayName: displayName,
            userEmail: userEmail,
            avatarURL: avatarURL,
            token: token
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
    /// keychain quota anomaly a write can fail, dropping the session on the next launch
    /// with no trace. We log at error level and forward to crash reporting so the failure
    /// is diagnosable. The success path is unchanged.
    private func reportKeychainFailure(_ status: OSStatus, operation: String) {
        guard KeychainStatus.isFailure(status) else { return }
        let error = KeychainStatus.error(status, operation: operation)
        AppLog.auth.error("Keychain \(operation, privacy: .public) failed: \(error.diagnosticMessage, privacy: .public)")
        AppCrashReporting.record(error, context: "auth.keychain.\(operation)")
    }
}

/// Pure classification + wrapping of keychain `OSStatus` results. Extracted as a seam so the
/// "is this an OSStatus worth reporting?" decision is unit-testable without touching Security.
enum KeychainStatus {
    /// A keychain op is a *reportable* failure when it is neither success nor the benign
    /// "nothing to delete" status (`errSecItemNotFound` — purging an already-absent item is
    /// the expected idempotent outcome, not an error).
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
    func read(service: String, account: String) -> Data?
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

    func read(service: String, account: String) -> Data? {
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

        if status == errSecSuccess {
            return dataTypeRef as? Data
        }
        return nil
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
