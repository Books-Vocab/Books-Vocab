import SwiftUI

struct SettingsPreferencesSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.PreferencesSection
    let actions: SettingsPresenterActions

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "偏好", icon: "slider.horizontal.3")

            VStack(spacing: 0) {
                // 外觀
                SettingsRow(icon: "circle.lefthalf.filled", label: "外觀") {
                    Menu {
                        ForEach(AppAppearanceMode.allCases) { mode in
                            Button {
                                actions.selectAppearance(mode)
                            } label: {
                                if state.selectedAppearance == mode.titleKey {
                                    Label(mode.titleKey, systemImage: "checkmark")
                                } else {
                                    Text(mode.titleKey)
                                }
                            }
                        }
                    } label: {
                        HStack(spacing: 6) {
                            Text(state.selectedAppearance)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                            Image(systemName: "chevron.up.chevron.down")
                                .font(vocabSkin.typography.iconTiny)
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("選擇外觀：\(state.selectedAppearance)")
                }

                SettingsDivider()

                // 語言
                SettingsRow(icon: "character.bubble", label: "語言") {
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
                        HStack(spacing: 6) {
                            Text(state.selectedLanguage)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                            Image(systemName: "chevron.up.chevron.down")
                                .font(vocabSkin.typography.iconTiny)
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("選擇語言：\(state.selectedLanguage)")
                }
            }
            .settingsCard()

            SettingsSectionFooter("切換後會立即套用到 app 介面。")
        }
    }
}
