//
//  AuthManager.swift
//  BooksBrowser
//
//  Created for Multi-User Apple Sign In
//

import SwiftUI
import Security
import Foundation
import GoogleSignIn
import SwiftData
import AuthenticationServices

@Observable
final class AuthManager: @unchecked Sendable, AuthManaging, AuthSessionProviding, SessionInvalidating {
    static let shared = AuthManager()

    @ObservationIgnored
    private let verifier: any AuthVerifying

    @ObservationIgnored
    private let localDataCleaner: any LocalDataClearing

    @ObservationIgnored
    var appleSignInDelegate: AppleSignInDelegate?

    // Stored at app startup so any logout path can clear local data
    var modelContainer: ModelContainer?

    // Status flag published to observers
    var isLoggedIn: Bool = false

    // For UI display of the user id or simple states
    var userId: String? {
        didSet { UserDefaults.standard.set(userId, forKey: "KGUserId") }
    }

    var displayName: String? {
        didSet { UserDefaults.standard.set(displayName, forKey: "KGDisplayName") }
    }

    var userEmail: String? {
        didSet { UserDefaults.standard.set(userEmail, forKey: "KGUserEmail") }
    }

    var avatarURL: URL? {
        didSet { UserDefaults.standard.set(avatarURL?.absoluteString, forKey: "KGAvatarURL") }
    }

    // Secure token memory
    var token: String?

    // Auth error to surface in UI
    var authError: String?

    init(
        verifier: any AuthVerifying = AuthBackendVerifier(),
        localDataCleaner: any LocalDataClearing = LocalDataCleanerService()
    ) {
        self.verifier = verifier
        self.localDataCleaner = localDataCleaner
        self.userId = UserDefaults.standard.string(forKey: "KGUserId")
        self.displayName = UserDefaults.standard.string(forKey: "KGDisplayName")
        self.userEmail = UserDefaults.standard.string(forKey: "KGUserEmail")
        if let urlStr = UserDefaults.standard.string(forKey: "KGAvatarURL") {
            self.avatarURL = URL(string: urlStr)
        }
        if let tokenData = KeychainHelper.standard.read(service: "kg-auth", account: "kgToken"),
           let tokenStr = String(data: tokenData, encoding: .utf8) {
            self.token = tokenStr
            self.isLoggedIn = true
        } else {
            self.isLoggedIn = false
        }
    }

    func login(userId: String, token: String) {
        let userIdStr = userId.trimmingCharacters(in: .whitespacesAndNewlines)
        let tokenStr = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !userIdStr.isEmpty, !tokenStr.isEmpty,
              let tokenData = tokenStr.data(using: .utf8) else { return }

        if let existing = self.userId, existing != userIdStr {
            print("🔄 Account switch detected (\(existing) → \(userIdStr)), clearing sync timestamp")
            UserDefaults.standard.removeObject(forKey: "kg_last_incremental_sync")
        }

        self.userId = userIdStr
        self.token = tokenStr
        _ = KeychainHelper.standard.save(tokenData, service: "kg-auth", account: "kgToken")
        self.isLoggedIn = true
    }

    func login(customToken: String) {
        login(userId: customToken, token: customToken)
    }

    func logout(modelContainer: ModelContainer? = nil, reason: String = "user_logout") {
        let container = modelContainer ?? self.modelContainer
        Task {
            if let container {
                await localDataCleaner.clearLocalData(container: container, reason: reason)
            }
            await MainActor.run {
                GIDSignIn.sharedInstance.signOut()
                self.userId = nil
                self.token = nil
                self.displayName = nil
                self.userEmail = nil
                self.avatarURL = nil
                KeychainHelper.standard.delete(service: "kg-auth", account: "kgToken")
                UserDefaults.standard.removeObject(forKey: "KGUserId")
                UserDefaults.standard.removeObject(forKey: "KGDisplayName")
                UserDefaults.standard.removeObject(forKey: "KGUserEmail")
                UserDefaults.standard.removeObject(forKey: "KGAvatarURL")
                self.isLoggedIn = false
            }
        }
    }

    @MainActor
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

        let isAccountSwitch = self.userId != nil && self.userId != userId
        if isAccountSwitch, let container = modelContainer {
            print("🧹 Account switch — clearing previous user's local data")
            await localDataCleaner.clearLocalData(container: container, reason: accountSwitchReason)
        }
        login(userId: userId, token: jwtToken)
    }

    @MainActor
    func setAuthError(_ message: String) {
        authError = message
    }

    func verify(provider: String, token: String, email: String?) async throws -> AuthVerificationResult {
        try await verifier.verify(provider: provider, token: token, email: email)
    }
}

// Simple Keychain Helper for secure storage
final class KeychainHelper {
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
