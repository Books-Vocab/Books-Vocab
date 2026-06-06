import Foundation
import SwiftData

@MainActor
protocol AuthSessionProviding: AnyObject {
    var isLoggedIn: Bool { get }
    var token: String? { get }
}

@MainActor
protocol SessionInvalidating: AnyObject {
    func logout(modelContainer: ModelContainer?, reason: String)
}

protocol LocalDataClearing: AnyObject {
    func clearLocalData(container: ModelContainer, reason: String) async
}

/// AuthManager 的行為契約，供 View / Handler 依賴，方便替換 Mock 進行測試
@MainActor
protocol AuthManaging: AnyObject {
    var isLoggedIn: Bool { get }
    var userId: String? { get }
    var token: String? { get }
    var displayName: String? { get }
    var userEmail: String? { get }
    var avatarURL: URL? { get }
    var authError: String? { get }
    var isAuthenticating: Bool { get }
    var isDemoMode: Bool { get }

    func enterDemoMode(modelContainer: ModelContainer)
    func exitDemoMode(modelContainer: ModelContainer)
    /// Re-reads the persisted session when a prior keychain read failed transiently
    /// (cold-boot, pre-first-unlock). Call when the app/scene becomes active.
    func refreshSessionIfNeeded()
    func login(userId: String, token: String)
    func login(customToken: String) async
    func logout(modelContainer: ModelContainer?, reason: String)
    func loginWithGoogle(modelContainer: ModelContainer?)
    func loginWithApple(modelContainer: ModelContainer?)
}
