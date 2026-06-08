#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

enum SettingsSubscriptionSectionScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings Subscription Section") {
            Scenario("Pro Active", layout: .fillH) {
                SubscriptionSectionScene(
                    state: SettingsPresenterPreviewData.subscribedActive.subscription!
                )
            }

            Scenario("Loading", layout: .fillH) {
                SubscriptionSectionScene(
                    state: SettingsPresenterPreviewData.subscriptionLoading.subscription!
                )
            }

            Scenario("Pricing Unavailable", layout: .fillH) {
                SubscriptionSectionScene(
                    state: SettingsPresenterPreviewData.pricingUnavailable.subscription!
                )
            }

            Scenario("Inactive · Free", layout: .fillH) {
                SubscriptionSectionScene(state: .inactiveFreeFixture)
            }
        }
    }
}

private struct SubscriptionSectionScene: View {
    let state: SettingsPresenterState.SubscriptionSection

    var body: some View {
        AppThemeContainer {
            ScrollView {
                SettingsSubscriptionSection(
                    state: state,
                    actions: SettingsPresenterPreviewData.noopActions
                )
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private extension SettingsPresenterState.SubscriptionSection {
    static var inactiveFreeFixture: SettingsPresenterState.SubscriptionSection {
        .init(
            isActive: false,
            planName: "免費方案",
            badgeText: "未訂閱",
            badgeTone: .neutral,
            summary: "升級 Pro 解鎖知識圖譜與播客。",
            detail: "目前使用免費額度，部分進階功能受限。",
            sourceLabel: "無",
            managementNote: "尚未訂閱，可隨時於 App Store 開始。",
            pricingUnavailableMessage: nil,
            restoreLabel: "恢復購買",
            restoreDescription: "曾經購買過？點此恢復先前的訂閱。",
            isRestoreAvailable: true,
            ctaTitle: "升級 Pro",
            isRefreshing: false
        )
    }
}
#endif
