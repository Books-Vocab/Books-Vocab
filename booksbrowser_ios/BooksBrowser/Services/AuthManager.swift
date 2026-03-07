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
import UIKit
import AuthenticationServices

@Observable
final class AuthManager: @unchecked Sendable, AuthManaging {
    static let shared = AuthManager()

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

    // Keep delegate alive during async Apple Sign-In flow
    private var appleSignInDelegate: AppleSignInDelegate?
    
    private init() {
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

        // Detect account switch — force full resync on next pull
        if let existing = self.userId, existing != userIdStr {
            print("🔄 Account switch detected (\(existing) → \(userIdStr)), clearing sync timestamp")
            UserDefaults.standard.removeObject(forKey: "kg_last_incremental_sync")
        }

        self.userId = userIdStr
        self.token = tokenStr

        _ = KeychainHelper.standard.save(tokenData, service: "kg-auth", account: "kgToken")

        self.isLoggedIn = true
    }

    // For backward compatibility with direct ID login
    func login(customToken: String) {
        login(userId: customToken, token: customToken)
    }
    
    // MARK: - Backend Verification

    @MainActor
    func verifyWithBackend(provider: String, token: String, email: String?, completion: @escaping (String?, String?) -> Void) {
        let serverURL = KGService.getServerURL()

        guard let url = URL(string: "\(serverURL)/auth/verify") else {
            print("❌ Invalid backend URL: \(serverURL)/auth/verify")
            completion(nil, nil)
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let payload: [String: Any] = [
            "provider": provider,
            "token": token,
            "email": email ?? NSNull()
        ]

        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        } catch {
            print("❌ Failed to encode auth payload: \(error)")
            completion(nil, nil)
            return
        }

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                print("❌ Backend verification error: \(error.localizedDescription)")
                completion(nil, nil)
                return
            }

            guard let data = data else {
                print("❌ No response data from backend")
                completion(nil, nil)
                return
            }

            do {
                if data.isEmpty {
                    print("❌ Response body is empty")
                    completion(nil, nil)
                    return
                }

                if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    let accessToken = json["access_token"] as? String
                    let userId = json["user_id"] as? String

                    if let accessToken = accessToken, let userId = userId {
                        print("✅ [verifyWithBackend] Got JWT and user_id")
                        completion(userId, accessToken)
                    } else {
                        print("❌ Invalid backend response: missing access_token or user_id")
                        print("   Keys in response: \(json.keys)")
                        completion(nil, nil)
                    }
                } else {
                    print("❌ Invalid JSON response format")
                    completion(nil, nil)
                }
            } catch {
                print("❌ Failed to parse backend response: \(error)")
                completion(nil, nil)
            }
        }.resume()
    }

    func logout(modelContainer: ModelContainer? = nil, reason: String = "user_logout") {
        let container = modelContainer ?? self.modelContainer
        Task {
            // 先清本地資料，再更新 isLoggedIn，確保 UI 重新顯示時詞庫已空
            if let container {
                await KGService().clearLocalData(container: container, reason: reason)
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
    
    // MARK: - Google Sign-In
    
    @MainActor
    func loginWithGoogle(modelContainer: ModelContainer? = nil) {
        let window = UIApplication.shared.connectedScenes.flatMap { ($0 as? UIWindowScene)?.windows ?? [] }.first { $0.isKeyWindow }
        guard let rootViewController = window?.rootViewController else {
            print("❌ Unable to find root view controller")
            return
        }

        GIDSignIn.sharedInstance.signIn(withPresenting: rootViewController) { [weak self] result, error in
            if let error = error {
                print("❌ Google Sign-In Error: \(error.localizedDescription)")
                return
            }

            guard let self, let user = result?.user else { return }

            let email = user.profile?.email ?? ""
            let name = user.profile?.name ?? ""
            let avatar = user.profile?.imageURL(withDimension: 100)
            print("✅ Google Sign-In Success")

            guard let idToken = user.idToken?.tokenString else {
                print("❌ Failed to get Google ID token")
                return
            }

            // Verify with backend
            Task { @MainActor in
                self.verifyWithBackend(provider: "google", token: idToken, email: email) { [weak self] userId, jwtToken in
                    guard let self, let userId, let jwtToken else {
                        print("❌ Backend verification failed")
                        DispatchQueue.main.async { self?.authError = "伺服器驗證失敗，請稍後再試。" }
                        return
                    }

                    DispatchQueue.main.async {
                        self.authError = nil
                        self.displayName = name.isEmpty ? nil : name
                        self.userEmail = email.isEmpty ? nil : email
                        self.avatarURL = avatar
                        let isAccountSwitch = self.userId != nil && self.userId != userId
                        if isAccountSwitch, let container = modelContainer {
                            print("🧹 Account switch — clearing previous user's local data")
                            Task { @MainActor in
                                await KGService().clearLocalData(container: container, reason: "account_switch_google")
                                self.login(userId: userId, token: jwtToken)
                            }
                        } else {
                            self.login(userId: userId, token: jwtToken)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Apple Sign-In

    @MainActor
    func loginWithApple(modelContainer: ModelContainer? = nil) {
        let request = ASAuthorizationAppleIDProvider().createRequest()
        request.requestedScopes = [.fullName, .email]

        let controller = ASAuthorizationController(authorizationRequests: [request])
        // Keep delegate alive by storing in instance variable
        self.appleSignInDelegate = AppleSignInDelegate(authManager: self, modelContainer: modelContainer)
        controller.delegate = self.appleSignInDelegate
        controller.performRequests()
    }
}

// MARK: - Apple Sign-In Delegate

private class AppleSignInDelegate: NSObject, ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    weak var authManager: AuthManager?
    let modelContainer: ModelContainer?

    init(authManager: AuthManager, modelContainer: ModelContainer? = nil) {
        self.authManager = authManager
        self.modelContainer = modelContainer
    }

    func authorizationController(controller: ASAuthorizationController,
                                 didCompleteWithAuthorization authorization: ASAuthorization) {
        if let appleIDCredential = authorization.credential as? ASAuthorizationAppleIDCredential {
            let email = appleIDCredential.email ?? ""

            // Apple 只在首次登入提供 fullName，需立即保存
            let nameComponents = appleIDCredential.fullName
            let fullName = [nameComponents?.givenName, nameComponents?.familyName]
                .compactMap { $0 }
                .joined(separator: " ")

            print("✅ Apple Sign-In Success")

            if email.isEmpty {
                print("⚠️ Apple didn't provide email. Creating new account without linking.")
            }

            completeAppleSignIn(identityToken: appleIDCredential.identityToken, email: email, displayName: fullName)
        }
    }

    private func completeAppleSignIn(identityToken: Data?, email: String, displayName: String = "") {
        guard let identityTokenData = identityToken,
              let identityToken = String(data: identityTokenData, encoding: .utf8) else {
            print("❌ Failed to get Apple identity token")
            return
        }

        // Verify with backend
        authManager?.verifyWithBackend(provider: "apple", token: identityToken, email: email) { [weak authManager] userId, jwtToken in
            guard let authManager, let userId, let jwtToken else {
                print("❌ Backend verification failed")
                DispatchQueue.main.async { authManager?.authError = "伺服器驗證失敗，請稍後再試。" }
                return
            }

            DispatchQueue.main.async {
                authManager.authError = nil
                // 只有首次登入 Apple 才提供 displayName/email，非空才覆蓋
                if !displayName.isEmpty { authManager.displayName = displayName }
                if !email.isEmpty { authManager.userEmail = email }
                authManager.avatarURL = nil  // Apple 不提供頭像

                let isAccountSwitch = authManager.userId != nil && authManager.userId != userId
                if isAccountSwitch, let container = self.modelContainer {
                    print("🧹 Account switch — clearing previous user's local data")
                    Task { @MainActor in
                        await KGService().clearLocalData(container: container, reason: "account_switch_apple")
                        authManager.login(userId: userId, token: jwtToken)
                    }
                } else {
                    authManager.login(userId: userId, token: jwtToken)
                }
            }
        }
    }


    func authorizationController(controller: ASAuthorizationController,
                                 didCompleteWithError error: Error) {
        print("❌ Apple Sign-In Error: \(error.localizedDescription)")
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        let window = UIApplication.shared.connectedScenes.flatMap { ($0 as? UIWindowScene)?.windows ?? [] }.first { $0.isKeyWindow }
        if let window = window {
            return window
        }
        
        let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene
        if let scene = windowScene {
            return UIWindow(windowScene: scene)
        }
        
        fatalError("No window scene found to present ASAuthorizationController")
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
        
        // Add data to keychain
        var status = SecItemAdd(query, nil)
        
        // If it exists, update it
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
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecClass: kSecClassGenericPassword,
            kSecReturnData: true
        ] as CFDictionary
        
        var result: AnyObject?
        SecItemCopyMatching(query, &result)
        
        return (result as? Data)
    }
    
    func delete(service: String, account: String) {
        let query = [
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecClass: kSecClassGenericPassword,
        ] as CFDictionary
        
        SecItemDelete(query)
    }
}
