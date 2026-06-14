#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `LoginSheet`.
///
/// `LoginSheet` reads `\.authManager` (a `@MainActor AuthManaging`) to drive its
/// error / authenticating states. Because `AuthManaging` is `@MainActor` and the
/// mock's init is therefore main-actor isolated, each scenario builds the mock
/// INSIDE a `View` body (main-actor isolated) via `LoginSheetScene`.
enum LoginSheetScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Login Sheet") {
            Scenario("Default", layout: .fill) {
                LoginSheetScene(authID: .guest)
            }
            Scenario("Authenticating", layout: .fill) {
                LoginSheetScene(authID: .guestAuthenticating)
            }
            Scenario("Error", layout: .fill) {
                LoginSheetScene(authID: .guestError)
            }
        }
    }
}

// MARK: - Scene harness

private struct LoginSheetScene: View {
    let authID: UIWorldAuthFixtureID

    var body: some View {
        let seed = FixtureDatasetStore.requireAuthSeed(for: authID)
        guard !seed.isLoggedIn else {
            preconditionFailure("UI World auth.\(authID.rawValue) must be logged out for LoginSheetScenarios")
        }
        let auth = CatalogPreviewAuth(
            isLoggedIn: seed.isLoggedIn,
            userId: seed.userId,
            token: seed.token,
            displayName: seed.displayName,
            userEmail: seed.email,
            isAuthenticating: seed.isAuthenticating,
            authError: seed.authError
        )
        return AppThemeContainer {
            LoginSheet()
                .environment(\.authManager, auth)
                .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
