#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SettingsAccountDetailView`.
///
/// 此 surface 是純值型 (`AuthSection` / `DangerSection` / `SettingsPresenterActions`)
/// 的展示，沒有 @MainActor init、不需 AuthManaging mock，也不接 SwiftData。
/// 直接餵既有 `SettingsPresenterPreviewData` fixtures + 合成 section，
/// 覆蓋 已登入(含資料管理/危險操作)、刪除中、登出(僅帳號資訊)、長字串壓力 四種狀態。
enum SettingsAccountDetailScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings Account Detail") {
            Scenario("Subscribed · active", layout: .fill) {
                AppThemeContainer {
                    NavigationStack {
                        SettingsAccountDetailView(
                            authState: SettingsPresenterPreviewData.subscribedActive.auth,
                            dangerState: SettingsPresenterPreviewData.subscribedActive.danger,
                            actions: SettingsPresenterPreviewData.noopActions
                        )
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Deleting account", layout: .fill) {
                AppThemeContainer {
                    NavigationStack {
                        SettingsAccountDetailView(
                            authState: SettingsPresenterPreviewData.deletingAccount.auth,
                            dangerState: SettingsPresenterPreviewData.deletingAccount.danger,
                            actions: SettingsPresenterPreviewData.noopActions
                        )
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Logged out · info only", layout: .fill) {
                AppThemeContainer {
                    NavigationStack {
                        SettingsAccountDetailView(
                            authState: SettingsAccountDetailScenarios.loggedOutAuth,
                            dangerState: nil,
                            actions: SettingsPresenterPreviewData.noopActions
                        )
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Long name & email stress", layout: .fill) {
                AppThemeContainer {
                    NavigationStack {
                        SettingsAccountDetailView(
                            authState: SettingsAccountDetailScenarios.longInfoAuth,
                            dangerState: SettingsPresenterState.DangerSection(isDeletingAccount: false),
                            actions: SettingsPresenterPreviewData.noopActions
                        )
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }

    // MARK: - Synthetic fixtures

    private static var loggedOutAuth: SettingsPresenterState.AuthSection {
        SettingsPresenterState.AuthSection(
            isLoggedIn: false,
            userInitials: nil,
            avatarURL: nil,
            displayName: "訪客",
            email: nil,
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        )
    }

    private static var longInfoAuth: SettingsPresenterState.AuthSection {
        SettingsPresenterState.AuthSection(
            isLoggedIn: true,
            userInitials: "WW",
            avatarURL: nil,
            displayName: "王小明的超級長英文混中文顯示名稱測試 Wonderfully Long Display Name",
            email: "an.extremely.long.email.address.for.layout.testing@example-domain.com",
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        )
    }
}
#endif
