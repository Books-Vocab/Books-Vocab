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
                LoginSheetScene()
            }
            Scenario("Authenticating", layout: .fill) {
                LoginSheetScene(isAuthenticating: true)
            }
            Scenario("Error", layout: .fill) {
                LoginSheetScene(authError: "無法連線至伺服器，請稍後再試。")
            }
        }
    }
}

// MARK: - Scene harness

private struct LoginSheetScene: View {
    var isAuthenticating: Bool = false
    var authError: String?

    var body: some View {
        let auth = PreviewAuthManager()
        auth.isAuthenticating = isAuthenticating
        auth.authError = authError
        return AppThemeContainer {
            LoginSheet()
                .environment(\.authManager, auth)
                .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Mock AuthManaging

/// Inert preview double for `AuthManaging`. All mutating calls are no-ops so the
/// catalog renders a stable, deterministic snapshot.
private final class PreviewAuthManager: AuthManaging {
    var isLoggedIn: Bool = false
    var userId: String?
    var token: String?
    var displayName: String?
    var userEmail: String?
    var avatarURL: URL?
    var authError: String?
    var isAuthenticating: Bool = false
    var isDemoMode: Bool = false

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
