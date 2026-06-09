//
//  CatalogPreviewAuth.swift
//  Books & Vocab
//
//  Shared DEBUG-only `AuthManaging` mock for the Playbook catalog.
//

#if DEBUG && canImport(Playbook)
import Foundation
import SwiftData

/// Deterministic `AuthManaging` mock for catalog scenarios.
///
/// Why: feature-screen scenarios must NOT render off the ambient
/// `AuthManager.shared` singleton — its `isLoggedIn` reflects whatever session
/// happens to be persisted on the snapshot simulator, so a scenario titled
/// "Logged out" can silently render a signed-in screen (the exact title↔pixel
/// drift that killed the old `SettingsView` surface). Injecting this mock via
/// `.environment(\.authManager, …)` pins the auth state to what the scenario
/// declares, regardless of simulator residue.
///
/// `AuthManaging` is `@MainActor`-isolated, so construct this inside a
/// `@MainActor` View body (the same place the in-memory `ModelContainer` is
/// seeded).
final class CatalogPreviewAuth: AuthManaging {
    var isLoggedIn: Bool
    var userId: String?
    var token: String?
    var displayName: String?
    var userEmail: String?
    var avatarURL: URL?
    var authError: String?
    var isAuthenticating: Bool
    var isDemoMode: Bool

    init(
        isLoggedIn: Bool,
        displayName: String? = nil,
        userEmail: String? = nil,
        isDemoMode: Bool = false,
        isAuthenticating: Bool = false,
        authError: String? = nil
    ) {
        self.isLoggedIn = isLoggedIn
        self.userId = isLoggedIn ? "preview-user" : nil
        self.token = isLoggedIn ? "preview-token" : nil
        self.displayName = displayName ?? (isLoggedIn ? "Preview User" : nil)
        self.userEmail = userEmail ?? (isLoggedIn ? "preview@example.com" : nil)
        self.avatarURL = nil
        self.authError = authError
        self.isAuthenticating = isAuthenticating
        self.isDemoMode = isDemoMode
    }

    func enterDemoMode(modelContainer: ModelContainer) {}
    func exitDemoMode(modelContainer: ModelContainer) {}
    func refreshSessionIfNeeded() {}
    func login(userId: String, token: String) {}
    func login(customToken: String) async {}
    func logout(modelContainer: ModelContainer?, reason: String) {}
    func loginWithGoogle(modelContainer: ModelContainer?) {}
    func loginWithApple(modelContainer: ModelContainer?) {}
}
#endif
