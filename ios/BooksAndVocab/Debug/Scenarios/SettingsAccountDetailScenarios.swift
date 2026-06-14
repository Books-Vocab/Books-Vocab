#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SettingsAccountDetailView`.
///
/// 此 surface 是純值型 (`AuthSection` / `DangerSection` / `SettingsPresenterActions`)
/// 的展示，沒有 @MainActor init、不需 AuthManaging mock，也不接 SwiftData。
/// 直接餵 UI World `settings.*` fixtures，覆蓋已登入(含資料管理/危險操作)、
/// 刪除中、登出(僅帳號資訊)、長字串壓力四種狀態。
enum SettingsAccountDetailScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings Account Detail") {
            Scenario("Subscribed · active", layout: .fill) {
                AccountDetailScene(fixtureID: .subscribedActive)
            }

            Scenario("Deleting account", layout: .fill) {
                AccountDetailScene(fixtureID: .deletingAccount)
            }

            Scenario("Logged out · info only", layout: .fill) {
                AccountDetailScene(fixtureID: .loggedOut)
            }

            Scenario("Long name & email stress", layout: .fill) {
                AccountDetailScene(fixtureID: .accountLongIdentity)
            }
        }
    }
}

private struct AccountDetailScene: View {
    let fixtureID: SettingsFixtureID

    private var state: SettingsPresenterState {
        SettingsFixtures.state(for: fixtureID)
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                SettingsAccountDetailView(
                    authState: state.auth,
                    dangerState: state.danger,
                    actions: SettingsPresenterPreviewData.noopActions
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
