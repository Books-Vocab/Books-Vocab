import SwiftUI

struct SettingsPreferencesSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.PreferencesSection
    let actions: SettingsPresenterActions
    let onShowTranslationLanguage: () -> Void
    let onShowReviewSettings: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "偏好".localized, icon: "slider.horizontal.3")

            VStack(spacing: 0) {
                // 外觀
                SettingsRow(icon: "circle.lefthalf.filled", label: "外觀".localized) {
                    Menu {
                        ForEach(AppAppearanceMode.allCases) { mode in
                            Button {
                                actions.selectAppearance(mode)
                            } label: {
                                if state.selectedAppearance == mode.titleKey {
                                    Label(mode.titleKey.localized, systemImage: "checkmark")
                                } else {
                                    Text(mode.titleKey.localized)
                                }
                            }
                        }
                    } label: {
                        SettingsMenuValue(text: state.selectedAppearance.localized)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\("選擇外觀".localized)：\(state.selectedAppearance.localized)")
                }

                SettingsDivider()

                // 翻譯語言
                Button(action: onShowTranslationLanguage) {
                    SettingsRow(icon: "textformat.abc", label: "翻譯語言") {
                        SettingsDisclosureValue(text: "\(state.translationSource) → \(state.translationTarget)")
                    }
                }
                .buttonStyle(.plain)

                SettingsDivider()

                // 語言
                SettingsRow(icon: "character.bubble", label: "語言".localized) {
                    Menu {
                        ForEach(AppLanguage.allCases) { language in
                            Button {
                                actions.selectLanguage(language)
                            } label: {
                                if state.selectedLanguage == L10n.string(language.titleKey) {
                                    Label(L10n.string(language.titleKey), systemImage: "checkmark")
                                } else {
                                    Text(L10n.string(language.titleKey))
                                }
                            }
                        }
                    } label: {
                        SettingsMenuValue(text: state.selectedLanguage)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\("選擇語言".localized)：\(state.selectedLanguage)")
                }

                SettingsDivider()

                // 複習節奏
                Button(action: onShowReviewSettings) {
                    SettingsRow(icon: "timer", label: "複習節奏") {
                        SettingsDisclosureValue(text: state.selectedReviewMode)
                    }
                }
                .buttonStyle(.plain)
            }
            .settingsCard()

            SettingsSectionFooter("切換後會立即套用到 app 介面。".localized)
        }
    }
}
