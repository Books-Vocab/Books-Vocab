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
            keychain.delete(service: Keys.tokenService, account: Keys.tokenAccount)
            return
        }
        _ = keychain.save(data, service: Keys.tokenService, account: Keys.tokenAccount)
    }

    func clearSession() {
        defaults.removeObject(forKey: Keys.userId)
        defaults.removeObject(forKey: Keys.displayName)
        defaults.removeObject(forKey: Keys.userEmail)
        defaults.removeObject(forKey: Keys.avatarURL)
        keychain.delete(service: Keys.tokenService, account: Keys.tokenAccount)
    }
}

protocol KeychainHelping: AnyObject {
    func save(_ data: Data, service: String, account: String) -> OSStatus
    func read(service: String, account: String) -> Data?
    func delete(service: String, account: String)
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

    func delete(service: String, account: String) {
        let query = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account
        ] as CFDictionary

        SecItemDelete(query)
    }
}
