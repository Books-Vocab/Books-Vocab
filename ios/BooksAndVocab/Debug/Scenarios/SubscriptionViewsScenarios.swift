#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SubscriptionViews.swift`.
///
/// 該檔目前唯一可渲染的 leaf view 是 `ProAccessGateCard`。它只吃純字串 +
/// 一個 closure，不依賴 SubscriptionManaging / SwiftData / 網路，因此直接餵
/// 合成文案即可覆蓋 happy / 長文壓力 / 窄寬 / Dynamic Type 等狀態。
enum SubscriptionViewsScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Subscription Views · Gate Card") {
            Scenario("Happy path", layout: .fillH) {
                GateCardScene(
                    title: "解鎖知識圖譜",
                    description: "升級至 Pro 即可使用知識圖譜、Today Review 與播客功能。",
                    actionTitle: "升級 Pro",
                    systemImage: "sparkles"
                )
            }
            Scenario("Long copy stress", layout: .fillH) {
                GateCardScene(
                    title: "解鎖完整 Pro 學習體驗與全部進階功能",
                    description: "升級後可無限使用知識圖譜連結推薦、每日 Today Review 排程複習、整本書播客生成、跨裝置同步詞庫，以及未來所有新增的進階學習工具。",
                    actionTitle: "立即升級至 Pro 解鎖全部功能",
                    systemImage: "graduationcap.fill"
                )
            }
            Scenario("Narrow width 320pt", layout: .fillH) {
                GateCardScene(
                    title: "解鎖 Today Review",
                    description: "升級至 Pro 解鎖間隔重複複習排程。",
                    actionTitle: "升級 Pro",
                    systemImage: "clock.badge.checkmark",
                    maxWidth: 320
                )
            }
            Scenario("Dynamic Type · accessibility3", layout: .fillH) {
                GateCardScene(
                    title: "解鎖播客",
                    description: "升級至 Pro 即可把整本書轉成播客。",
                    actionTitle: "升級 Pro",
                    systemImage: "headphones"
                )
                .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

private struct GateCardScene: View {
    @Environment(\.appSkin) private var appSkin

    let title: String
    let description: String
    let actionTitle: String
    let systemImage: String
    var maxWidth: CGFloat? = nil

    var body: some View {
        AppThemeContainer {
            ProAccessGateCard(
                title: title,
                description: description,
                actionTitle: actionTitle,
                systemImage: systemImage,
                onAction: {}
            )
            .frame(maxWidth: maxWidth)
            .padding()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(appSkin.palette.pageBackground.ignoresSafeArea())
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
