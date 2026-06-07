#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Settings control primitives defined in
/// `SettingsPresenter+Controls.swift`:
/// - `SettingsStepperIconButton` (enabled / disabled)
/// - view-modifiers `settingsCard()` / `appSettingsButtonChrome()` /
///   `appSettingsTextInputStyle()` applied to sample content
/// - `SettingsLabeledInputField` wrapper
enum SettingsControlsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Stepper Icon Buttons
        playbook.addScenarios(of: "Settings Controls · Stepper") {
            Scenario("Enabled pair", layout: .fill) {
                AppThemeContainer {
                    HStack(spacing: 16) {
                        SettingsStepperIconButton(systemImage: "minus", enabled: true, action: {})
                        SettingsStepperIconButton(systemImage: "plus", enabled: true, action: {})
                    }
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Disabled pair", layout: .fill) {
                AppThemeContainer {
                    HStack(spacing: 16) {
                        SettingsStepperIconButton(systemImage: "minus", enabled: false, action: {})
                        SettingsStepperIconButton(systemImage: "plus", enabled: false, action: {})
                    }
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Mixed bound", layout: .fill) {
                AppThemeContainer {
                    HStack(spacing: 16) {
                        SettingsStepperIconButton(systemImage: "minus", enabled: false, action: {})
                        Text("1")
                            .font(.title3.monospacedDigit())
                            .frame(minWidth: 40)
                        SettingsStepperIconButton(systemImage: "plus", enabled: true, action: {})
                    }
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Container Modifiers
        playbook.addScenarios(of: "Settings Controls · Modifiers") {
            Scenario("settingsCard()", layout: .fill) {
                AppThemeContainer {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("卡片容器")
                            .font(.headline)
                        Text("settingsCard() 套用 AppSectionCard 的 settings 樣式。")
                            .font(.footnote)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .settingsCard()
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("appSettingsButtonChrome()", layout: .fill) {
                AppThemeContainer {
                    Text("按鈕 Chrome 容器")
                        .font(.body)
                        .frame(maxWidth: .infinity)
                        .appSettingsButtonChrome()
                        .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("appSettingsTextInputStyle()", layout: .fill) {
                AppThemeContainer {
                    VStack(spacing: 16) {
                        Text("0.85")
                            .frame(maxWidth: .infinity)
                            .appSettingsTextInputStyle()
                            .appSettingsButtonChrome()
                        Text("centered")
                            .frame(maxWidth: .infinity)
                            .appSettingsTextInputStyle(alignment: .center)
                            .appSettingsButtonChrome()
                    }
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Labeled Input Field
        playbook.addScenarios(of: "Settings Controls · Input Field") {
            Scenario("Editable field", layout: .fill) {
                LabeledInputFieldScene(title: "每日複習上限", initial: "20")
            }
            Scenario("Empty value", layout: .fill) {
                LabeledInputFieldScene(title: "自訂閾值", initial: "")
            }
        }
    }
}

// MARK: - Scene harnesses

private struct LabeledInputFieldScene: View {
    let title: String
    @State private var value: String

    init(title: String, initial: String) {
        self.title = title
        self._value = State(initialValue: initial)
    }

    var body: some View {
        AppThemeContainer {
            SettingsLabeledInputField(title: title) {
                TextField("", text: $value)
                    .appSettingsTextInputStyle()
            }
            .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
