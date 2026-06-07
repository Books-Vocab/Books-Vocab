#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the three Settings view-modifiers defined in
/// `SettingsPresenter+Controls.swift`:
/// - `SettingsButtonChromeModifier` (via `.appSettingsButtonChrome()` and direct `.modifier`)
/// - `SettingsCardModifier` (via `.settingsCard()` and direct `.modifier`)
/// - `SettingsTextInputModifier` (via direct `.modifier` to exercise the struct by name)
///
/// All three modifiers are `ViewModifier` structs that read `@Environment(\.appSkin)`;
/// none have @MainActor-isolated inits, so plain helper views are safe.
enum SettingsModifierScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Button Chrome
        playbook.addScenarios(of: "Settings Modifiers · Button Chrome") {
            Scenario("Convenience method", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        Text("匯出詞庫")
                            .appSettingsButtonChrome()
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Direct modifier — icon + label", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        HStack(spacing: 8) {
                            Image(systemName: "arrow.down.circle")
                            Text("下載最新資料")
                        }
                        .modifier(SettingsButtonChromeModifier())
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Stepper buttons", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        HStack(spacing: 12) {
                            SettingsStepperIconButton(systemImage: "minus", enabled: true, action: {})
                            Text("12")
                                .modifier(SettingsTextInputModifier(alignment: .center))
                            SettingsStepperIconButton(systemImage: "plus", enabled: false, action: {})
                        }
                        .modifier(SettingsButtonChromeModifier())
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Card
        playbook.addScenarios(of: "Settings Modifiers · Card") {
            Scenario("Convenience method", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("帳號")
                            Text("已登入 — booksbrowsertest")
                        }
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .settingsCard()
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Direct modifier — row stack", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        VStack(spacing: 0) {
                            ForEach(["翻譯語言", "複習提醒", "知識圖譜密度"], id: \.self) { label in
                                HStack {
                                    Text(label)
                                    Spacer()
                                    Image(systemName: "chevron.right")
                                }
                                .padding()
                            }
                        }
                        .modifier(SettingsCardModifier())
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Text Input
        playbook.addScenarios(of: "Settings Modifiers · Text Input") {
            Scenario("Trailing alignment (default)", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        SettingsLabeledInputField(title: "每日複習上限") {
                            Text("50")
                                .modifier(SettingsTextInputModifier(alignment: .trailing))
                        }
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Center alignment", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        SettingsLabeledInputField(title: "間隔天數") {
                            Text("7")
                                .modifier(SettingsTextInputModifier(alignment: .center))
                        }
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Convenience method — leading", layout: .fill) {
                AppThemeContainer {
                    SettingsModifierSampleScene {
                        SettingsLabeledInputField(title: "API 端點") {
                            Text("https://wordnexus.lol")
                                .appSettingsTextInputStyle(alignment: .leading)
                        }
                    }
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}

// MARK: - Scene harness

/// Centers a single sample view on the page background so each modifier's
/// chrome (border / fill / corner radius / typography) is the focal point.
private struct SettingsModifierSampleScene<Content: View>: View {
    @Environment(\.appSkin) private var appSkin
    @ViewBuilder let content: Content

    var body: some View {
        VStack {
            content
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(appSkin.palette.pageBackground)
    }
}
#endif
