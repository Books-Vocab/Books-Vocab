//
//  AuthManager.swift
//  BooksBrowser
//
//  Created for Multi-User Apple Sign In
//

import SwiftUI
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

    init(
        verifier: any AuthVerifying = AuthBackendVerifier(),
        localDataCleaner: any LocalDataClearing = LocalDataCleanerService(),
        sessionStore: any AuthSessionStoring = AuthSessionStore()
    ) {
        self.verifier = verifier
        self.localDataCleaner = localDataCleaner
        self.sessionStore = sessionStore
        let persisted = sessionStore.loadSession()
        self.userId = persisted.userId
        self.displayName = persisted.displayName
        self.userEmail = persisted.userEmail
        self.avatarURL = persisted.avatarURL
        self.token = persisted.token
        self.isLoggedIn = persisted.token != nil
    }

    func login(userId: String, token: String) {
        let userIdStr = userId.trimmingCharacters(in: .whitespacesAndNewlines)
        let tokenStr = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !userIdStr.isEmpty, !tokenStr.isEmpty else { return }

        if let existing = self.userId, existing != userIdStr {
            print("🔄 Account switch detected (\(existing) → \(userIdStr)), clearing sync timestamp")
            UserDefaults.standard.removeObject(forKey: "kg_last_incremental_sync")
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
                self.sessionStore.clearSession()
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
        sessionStore.persistProfile(
            userId: self.userId,
            displayName: self.displayName,
            userEmail: self.userEmail,
            avatarURL: self.avatarURL
        )

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
