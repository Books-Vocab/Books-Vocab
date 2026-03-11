import Foundation
import GoogleSignIn
import SwiftData
import UIKit
import os

extension AuthManager {
    func loginWithGoogle(modelContainer: ModelContainer? = nil) {
        let window = UIApplication.shared.connectedScenes
            .flatMap { ($0 as? UIWindowScene)?.windows ?? [] }
            .first { $0.isKeyWindow }
        guard let presentingViewController = window?.rootViewController?.topMostPresentedViewController else {
            AppLog.auth.error("Unable to find presenting view controller")
            return
        }

        GIDSignIn.sharedInstance.signIn(withPresenting: presentingViewController) { [weak self] result, error in
            if let error = error {
                AppLog.auth.error("Google Sign-In error: \(error.localizedDescription)")
                return
            }

            guard let self, let user = result?.user else { return }

            let email = user.profile?.email ?? ""
            let name = user.profile?.name ?? ""
            let avatar = user.profile?.imageURL(withDimension: 100)
            AppLog.auth.info("Google Sign-In success")

            guard let idToken = user.idToken?.tokenString else {
                AppLog.auth.error("Failed to get Google ID token")
                return
            }

            Task { @MainActor [weak self] in
                guard let self else { return }
                self.isAuthenticating = true
                defer { self.isAuthenticating = false }
                do {
                    let verification = try await self.verify(provider: "google", token: idToken, email: email)
                    await self.applyAuthenticatedUser(
                        userId: verification.userId,
                        jwtToken: verification.accessToken,
                        displayName: name.isEmpty ? nil : name,
                        email: email.isEmpty ? nil : email,
                        avatarURL: avatar,
                        accountSwitchReason: "account_switch_google",
                        modelContainer: modelContainer
                    )
                } catch {
                    AppLog.auth.error("Backend verification failed: \(error.localizedDescription)")
                    self.setAuthError(L10n.string("伺服器驗證失敗，請稍後再試。"))
                }
            }
        }
    }
}

private extension UIViewController {
    var topMostPresentedViewController: UIViewController {
        if let presentedViewController {
            return presentedViewController.topMostPresentedViewController
        }
        if let navigationController = self as? UINavigationController {
            return navigationController.visibleViewController?.topMostPresentedViewController ?? navigationController
        }
        if let tabBarController = self as? UITabBarController {
            return tabBarController.selectedViewController?.topMostPresentedViewController ?? tabBarController
        }
        return self
    }
}
