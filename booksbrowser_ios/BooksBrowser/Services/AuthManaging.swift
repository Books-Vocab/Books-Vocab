import Foundation
import SwiftData

protocol AuthSessionProviding: AnyObject {
    var isLoggedIn: Bool { get }
    var token: String? { get }
}

protocol SessionInvalidating: AnyObject {
    func logout(modelContainer: ModelContainer?, reason: String)
}

protocol LocalDataClearing: AnyObject {
    func clearLocalData(container: ModelContainer, reason: String) async
}

/// AuthManager 的行為契約，供 View / Handler 依賴，方便替換 Mock 進行測試
@preconcurrency protocol AuthManaging: AnyObject {
    var isLoggedIn: Bool { get }
    var userId: String? { get }
    var token: String? { get }
    var displayName: String? { get }
    var userEmail: String? { get }
    var avatarURL: URL? { get }
    var authError: String? { get }

    func login(userId: String, token: String)
    func login(customToken: String)
    func logout(modelContainer: ModelContainer?, reason: String)
    @MainActor func loginWithGoogle(modelContainer: ModelContainer?)
    @MainActor func loginWithApple(modelContainer: ModelContainer?)
}
