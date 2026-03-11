import Foundation
import SwiftData
import UIKit
import AuthenticationServices

extension AuthManager {
    func loginWithApple(modelContainer: ModelContainer? = nil) {
        let request = ASAuthorizationAppleIDProvider().createRequest()
        request.requestedScopes = [.fullName, .email]

        let controller = ASAuthorizationController(authorizationRequests: [request])
        let delegate = AppleSignInDelegate(
            authManager: self,
            modelContainer: modelContainer
        )
        appleSignInDelegate = delegate
        controller.delegate = delegate
        controller.presentationContextProvider = delegate
        controller.performRequests()
    }
}

final class AppleSignInDelegate: NSObject, ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    weak var authManager: AuthManager?
    let modelContainer: ModelContainer?

    init(authManager: AuthManager, modelContainer: ModelContainer? = nil) {
        self.authManager = authManager
        self.modelContainer = modelContainer
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard let appleIDCredential = authorization.credential as? ASAuthorizationAppleIDCredential else {
            return
        }

        let email = appleIDCredential.email ?? ""
        let nameComponents = appleIDCredential.fullName
        let fullName = [nameComponents?.givenName, nameComponents?.familyName]
            .compactMap { $0 }
            .joined(separator: " ")

        print("✅ Apple Sign-In Success")
        if email.isEmpty {
            print("⚠️ Apple didn't provide email. Creating new account without linking.")
        }

        Task { @MainActor [weak self] in
            guard let self, let authManager else { return }
            authManager.isAuthenticating = true
            defer { authManager.isAuthenticating = false }
            do {
                guard
                    let identityTokenData = appleIDCredential.identityToken,
                    let identityToken = String(data: identityTokenData, encoding: .utf8)
                else {
                    print("❌ Failed to get Apple identity token")
                    return
                }

                let verification = try await authManager.verify(
                    provider: "apple",
                    token: identityToken,
                    email: email
                )

                await authManager.applyAuthenticatedUser(
                    userId: verification.userId,
                    jwtToken: verification.accessToken,
                    displayName: fullName.isEmpty ? nil : fullName,
                    email: email.isEmpty ? nil : email,
                    avatarURL: nil,
                    accountSwitchReason: "account_switch_apple",
                    modelContainer: modelContainer
                )
            } catch {
                print("❌ Backend verification failed: \(error)")
                authManager.setAuthError(L10n.string("伺服器驗證失敗，請稍後再試。"))
            }
        }
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        print("❌ Apple Sign-In Error: \(error.localizedDescription)")
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        let window = UIApplication.shared.connectedScenes
            .flatMap { ($0 as? UIWindowScene)?.windows ?? [] }
            .first { $0.isKeyWindow }
        if let window {
            return window
        }

        if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene {
            return UIWindow(windowScene: scene)
        }

        fatalError("No window scene found to present ASAuthorizationController")
    }
}
