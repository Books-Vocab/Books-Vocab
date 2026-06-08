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
        let auth = CatalogPreviewAuth(
            isLoggedIn: false,
            isAuthenticating: isAuthenticating,
            authError: authError
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
