#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenario for the settings plan-comparison table declared in
/// `SettingsPresenter+Actions.swift` (`SettingsPlanComparisonTable`).
///
/// Pure value-driven view reading `@Environment(\.appSkin)` (supplied by
/// AppThemeContainer); no @MainActor construction is involved.
enum SettingsActionsScenarios {
    static func register(in playbook: Playbook) {
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
#endif
