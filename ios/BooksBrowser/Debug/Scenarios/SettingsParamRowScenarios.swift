#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SettingsReviewSection.ParamRow` — a labeled value row
/// with a minus / plus stepper pair, used in the custom review-interval card.
/// `ParamRow` consumes only plain values (label / value strings, Bool enabled
/// flags, void closures) so each scenario constructs it directly inside the
/// nonisolated Scenario closure (no @MainActor scene harness needed).
enum SettingsParamRowScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Settings · ParamRow") {
            Scenario("Both enabled", layout: .compressed) {
                AppThemeContainer {
                    SettingsReviewSection.ParamRow(
                        label: "初始間隔",
                        value: "24h",
                        onDecrement: {},
                        onIncrement: {},
                        canDecrement: true,
                        canIncrement: true
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("At minimum", layout: .compressed) {
                AppThemeContainer {
                    SettingsReviewSection.ParamRow(
                        label: "最短間隔",
                        value: "1h",
                        onDecrement: {},
                        onIncrement: {},
                        canDecrement: false,
                        canIncrement: true
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("At maximum", layout: .compressed) {
                AppThemeContainer {
                    SettingsReviewSection.ParamRow(
                        label: "最長間隔",
                        value: "365天",
                        onDecrement: {},
                        onIncrement: {},
                        canDecrement: true,
                        canIncrement: false
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Both disabled", layout: .compressed) {
                AppThemeContainer {
                    SettingsReviewSection.ParamRow(
                        label: "記得倍率",
                        value: "2.50×",
                        onDecrement: {},
                        onIncrement: {},
                        canDecrement: false,
                        canIncrement: false
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Long label", layout: .compressed) {
                AppThemeContainer {
                    SettingsReviewSection.ParamRow(
                        label: "忘記後重置至最短間隔的倍率係數",
                        value: "0.50×",
                        onDecrement: {},
                        onIncrement: {},
                        canDecrement: true,
                        canIncrement: true
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif