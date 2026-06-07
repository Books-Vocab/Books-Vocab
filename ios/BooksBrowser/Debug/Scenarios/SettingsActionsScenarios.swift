#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the settings action / subscription building blocks
/// declared in `SettingsPresenter+Actions.swift`:
/// SettingsCompactActionButton, SettingsInlineInfoButton,
/// SettingsSubscriptionInfoBlock, SettingsSubscriptionFeatureList,
/// SettingsPlanComparisonTable.
///
/// All components are pure value-driven views reading `@Environment(\.appSkin)`
/// (supplied by AppThemeContainer); no @MainActor construction is involved.
enum SettingsActionsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Compact buttons + inline info
        playbook.addScenarios(of: "Settings Actions · Buttons") {
            Scenario("Compact action — enabled", layout: .fill) {
                AppThemeContainer {
                    VStack(spacing: 16) {
                        SettingsCompactActionButton(title: "管理訂閱") {}
                        SettingsCompactActionButton(title: "還原購買") {}
                        SettingsCompactActionButton(title: "登出") {}
                    }
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Compact action — disabled", layout: .fill) {
                AppThemeContainer {
                    VStack(spacing: 16) {
                        SettingsCompactActionButton(title: "還原購買", isEnabled: false) {}
                        SettingsCompactActionButton(title: "已是最新版本", isEnabled: false) {}
                    }
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Inline info button", layout: .fill) {
                AppThemeContainer {
                    HStack(spacing: 12) {
                        Text("每日複習額度")
                        SettingsInlineInfoButton {}
                    }
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Subscription info block + feature list
        playbook.addScenarios(of: "Settings Actions · Subscription") {
            Scenario("Info block — full", layout: .fill) {
                AppThemeContainer {
                    SettingsSubscriptionInfoBlock(
                        title: "WordNexus Pro",
                        subtitle: "無限詞庫、知識圖譜與每日複習",
                        detail: "下次扣款日：2026 年 7 月 7 日",
                        titleFont: .title3.weight(.semibold)
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Info block — title only", layout: .fill) {
                AppThemeContainer {
                    SettingsSubscriptionInfoBlock(
                        title: "免費方案",
                        titleFont: .title3.weight(.semibold)
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Feature list", layout: .fill) {
                AppThemeContainer {
                    SettingsSubscriptionFeatureListScene.standard
                        .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Feature list — single item", layout: .fill) {
                AppThemeContainer {
                    SettingsSubscriptionFeatureListScene.single
                        .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Plan comparison table
        playbook.addScenarios(of: "Settings Actions · Plan Table") {
            Scenario("Free vs Pro", layout: .fill) {
                AppThemeContainer {
                    SettingsPlanComparisonTable(rows: SettingsActionsScenarios.comparisonRows)
                        .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Free vs Pro — short", layout: .fill) {
                AppThemeContainer {
                    SettingsPlanComparisonTable(rows: Array(SettingsActionsScenarios.comparisonRows.prefix(2)))
                        .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }

    // MARK: - Fixtures

    fileprivate static var featureItems: [SettingsSubscriptionFeatureItem] {
        [
            SettingsSubscriptionFeatureItem(
                title: "無限詞庫",
                description: "不限儲存的單字與例句",
                icon: "books.vertical.fill",
                tone: .accentColor
            ),
            SettingsSubscriptionFeatureItem(
                title: "知識圖譜",
                description: "自動連結相關詞彙",
                icon: "point.3.connected.trianglepath.dotted",
                tone: .accentColor
            ),
            SettingsSubscriptionFeatureItem(
                title: "每日複習",
                description: nil,
                icon: "calendar",
                tone: .accentColor
            ),
        ]
    }

    fileprivate static var comparisonRows: [SettingsPlanComparisonRow] {
        [
            SettingsPlanComparisonRow(title: "詞庫容量", freeMark: .label("100"), proMark: .label("無限")),
            SettingsPlanComparisonRow(title: "知識圖譜", freeMark: .cross, proMark: .check),
            SettingsPlanComparisonRow(title: "每日複習額度", freeMark: .label("10"), proMark: .label("無限")),
            SettingsPlanComparisonRow(title: "Podcast 生成", freeMark: .cross, proMark: .check),
            SettingsPlanComparisonRow(title: "雲端同步", freeMark: .check, proMark: .check),
        ]
    }
}

// MARK: - Scene helpers

private enum SettingsSubscriptionFeatureListScene {
    static var standard: SettingsSubscriptionFeatureList {
        SettingsSubscriptionFeatureList(
            borderTone: .accentColor,
            items: SettingsActionsScenarios.featureItems
        )
    }

    static var single: SettingsSubscriptionFeatureList {
        SettingsSubscriptionFeatureList(
            borderTone: .accentColor,
            items: [SettingsActionsScenarios.featureItems[0]]
        )
    }
}
#endif
