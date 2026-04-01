import Foundation
import SwiftData
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif
import AuthenticationServices
import os

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

        AppLog.auth.info("Apple Sign-In success")
        if email.isEmpty {
            AppLog.auth.warning("Apple didn't provide email. Creating new account without linking.")
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
                    AppLog.auth.error("Failed to get Apple identity token")
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
                AppAnalytics.track(.loginCompleted(provider: "apple"))
            } catch {
                AppLog.auth.error("Backend verification failed: \(error.localizedDescription)")
                authManager.setAuthError(L10n.string("伺服器驗證失敗，請稍後再試。"))
                AppAnalytics.track(.loginFailed(provider: "apple", error: error.localizedDescription))
            }
        }
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        AppLog.auth.error("Apple Sign-In error: \(error.localizedDescription)")
        AppAnalytics.track(.loginFailed(provider: "apple", error: error.localizedDescription))
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        #if os(iOS)
        let window = UIApplication.shared.connectedScenes
            .flatMap { ($0 as? UIWindowScene)?.windows ?? [] }
            .first { $0.isKeyWindow }
        if let window {
            return window
        }

        guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene else {
            preconditionFailure("No UIWindowScene available for ASAuthorizationController")
        }
        return UIWindow(windowScene: scene)
        #elseif os(macOS)
        return NSApplication.shared.keyWindow ?? NSWindow()
        #endif
    }
}
