import SwiftUI

struct SettingsPreferencesSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let state: SettingsPresenterState.PreferencesSection
    let actions: SettingsPresenterActions
    let onShowTranslationLanguage: () -> Void
    let onShowReviewSettings: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "偏好".localized, icon: "slider.horizontal.3")

            VStack(spacing: 0) {
                // 外觀
                AppKeyValueRow(icon: "circle.lefthalf.filled", label: "外觀".localized, style: .settings(appSkin)) {
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
                SettingsNavigationRow(
                    icon: "textformat.abc",
                    label: "翻譯語言",
                    action: onShowTranslationLanguage
                ) {
                    SettingsStatusValue(
                        text: "\(state.translationSource) → \(state.translationTarget)",
                        color: appSkin.palette.secondaryText
                    )
                    .accessibilityIdentifier("settings.preferences.translationLanguageValue")
                }
                .accessibilityIdentifier("settings.preferences.translationLanguageRow")

                SettingsDivider()

                // 語言
                AppKeyValueRow(icon: "character.bubble", label: "語言".localized, style: .settings(appSkin)) {
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
                SettingsNavigationRow(
                    icon: "timer",
                    label: "複習節奏",
                    action: onShowReviewSettings
                ) {
                    SettingsStatusValue(
                        text: state.selectedReviewMode,
                        color: appSkin.palette.secondaryText
                    )
                    .accessibilityIdentifier("settings.preferences.reviewRhythmValue")
                }
                .accessibilityIdentifier("settings.preferences.reviewRhythmRow")

                SettingsDivider()

                AppKeyValueRow(
                    icon: "speaker.wave.2",
                    label: FeedbackSettingsCopy.soundTitle,
                    style: .settings(appSkin)
                ) {
                    Toggle(FeedbackSettingsCopy.soundTitle, isOn: Binding(
                        get: { state.soundFeedbackEnabled },
                        set: { actions.toggleSoundFeedback($0) }
                    ))
                    .labelsHidden()
                    .tint(appSkin.palette.accent)
                    .accessibilityIdentifier("settings.preferences.soundFeedbackToggle")
                }

                SettingsDivider()

                AppKeyValueRow(
                    icon: "hand.tap",
                    label: FeedbackSettingsCopy.hapticTitle,
                    style: .settings(appSkin)
                ) {
                    Toggle(FeedbackSettingsCopy.hapticTitle, isOn: Binding(
                        get: { state.hapticFeedbackEnabled },
                        set: { actions.toggleHapticFeedback($0) }
                    ))
                    .labelsHidden()
                    .tint(appSkin.palette.accent)
                    .accessibilityIdentifier("settings.preferences.hapticFeedbackToggle")
                }

                if state.showAutoSync {
                    SettingsDivider()

                    AppKeyValueRow(
                        icon: "arrow.triangle.2.circlepath",
                        label: "自動同步".localized,
                        style: .settings(appSkin)
                    ) {
                        Toggle("", isOn: Binding(
                            get: { state.autoSyncEnabled },
                            set: { actions.toggleAutoSync($0) }
                        ))
                        .labelsHidden()
                        .tint(appSkin.palette.accent)
                    }
                }

                if state.showAutoLink {
                    SettingsDivider()

                    AppKeyValueRow(
                        icon: "point.3.connected.trianglepath.dotted",
                        label: "自動連結".localized,
                        style: .settings(appSkin)
                    ) {
                        Toggle("", isOn: Binding(
                            get: { state.autoLinkEnabled },
                            set: { actions.toggleAutoLink($0) }
                        ))
                        .labelsHidden()
                        .tint(appSkin.palette.accent)
                        .accessibilityIdentifier("settings.preferences.autoLinkToggle")
                    }
                }
            }
            .settingsCard()

            SettingsSectionFooter(footerText)
        }
        .enableInjection()
    }

    /// 沿用既有兩段 footer 文案（含自動同步說明的組合 key 不拆，保留既有翻譯），
    /// 顯示自動連結 toggle 時追加一句說明。
    private var footerText: String {
        var text = state.showAutoSync
            ? "切換後會立即套用到 app 介面。開啟自動同步後，收錄滿 5 個單字會自動同步到雲端。".localized
            : "切換後會立即套用到 app 介面。".localized
        if state.showAutoLink {
            text += "關閉自動連結後，新單字不再自動建立知識圖譜連結；重新開啟會繼續處理累積的單字。".localized
        }
        return text
    }
}
