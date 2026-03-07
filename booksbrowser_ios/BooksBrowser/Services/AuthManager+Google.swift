import Foundation
import GoogleSignIn
import SwiftData
import UIKit

extension AuthManager {
    @MainActor
    func loginWithGoogle(modelContainer: ModelContainer? = nil) {
        let window = UIApplication.shared.connectedScenes
            .flatMap { ($0 as? UIWindowScene)?.windows ?? [] }
            .first { $0.isKeyWindow }
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

            Task { @MainActor [weak self] in
                guard let self else { return }
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
                    print("❌ Backend verification failed: \(error)")
                    self.setAuthError("伺服器驗證失敗，請稍後再試。")
                }
            }
        }
    }
}
