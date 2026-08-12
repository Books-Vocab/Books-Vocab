import SwiftUI

struct SettingsPreferencesSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.reviewCardLayoutStore) private var reviewCardLayoutStore
    /// 與正上方「複習卡片」列同一個做法：摘要值直接讀 store，不經 state 轉一手。
    @Environment(\.readerSettings) private var readerSettings
    let state: SettingsPresenterState.PreferencesSection
    let actions: SettingsPresenterActions
    let onShowTranslationLanguage: () -> Void
    let onShowReviewSettings: () -> Void
    /// Card presentation, deliberately its own row rather than a page inside
    /// 複習節奏 — that page owns SRS scheduling rules, not what a card looks like.
    var onShowReviewCardLayout: () -> Void = {}
    /// 閱讀設定 — 與「複習卡片」同一種列。閱讀器 chrome 的入口是情境入口
    /// （看著書調），這裡是偏好入口（平常調），兩者都保留，也都指向同一頁。
    var onShowReaderSettings: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            appearancePreferencesGroup
            learningPreferencesGroup
            feedbackPreferencesGroup
            readerPreferencesGroup
            if state.showAutoSync || state.showAutoLink {
                syncPreferencesGroup
            }

            SettingsSectionFooter(footerText)
        }
        .enableInjection()
    }

    private var appearancePreferencesGroup: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("介面與語言"), icon: "slider.horizontal.3")

            VStack(spacing: 0) {
                appearanceRow
                SettingsDivider()
                languageRow
            }
            .settingsCard()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.preferences.appearanceGroup")
    }

    private var learningPreferencesGroup: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("學習與複習"), icon: "graduationcap")

            VStack(spacing: 0) {
                reviewRhythmRow
                SettingsDivider()
                reviewCardLayoutRow
            }
            .settingsCard()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.preferences.learningGroup")
    }

    private var feedbackPreferencesGroup: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("互動回饋"), icon: "hand.tap")

            VStack(spacing: 0) {
                soundFeedbackRow
                SettingsDivider()
                hapticFeedbackRow
            }
            .settingsCard()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.preferences.feedbackGroup")
    }

    private var readerPreferencesGroup: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("閱讀介面"), icon: "book")

            VStack(spacing: 0) {
                translationLanguageRow
                SettingsDivider()
                readerSettingsRow
            }
            .settingsCard()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.preferences.readerGroup")
    }

    private var syncPreferencesGroup: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(
                title: L10n.string("雲端同步與跨裝置狀態"),
                icon: "arrow.triangle.2.circlepath"
            )

            VStack(spacing: 0) {
                if state.showAutoSync {
                    autoSyncRow
                }

                if state.showAutoSync && state.showAutoLink {
                    SettingsDivider()
                }

                if state.showAutoLink {
                    autoLinkRow
                }
            }
            .settingsCard()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.preferences.syncGroup")
    }

    private var appearanceRow: some View {
        AppKeyValueRow(icon: "circle.lefthalf.filled", label: L10n.string("外觀"), style: .settings(appSkin)) {
            Menu {
                ForEach(AppAppearanceMode.allCases) { mode in
                    Button {
                        actions.selectAppearance(mode)
                    } label: {
                        if state.selectedAppearance == mode.titleKey {
                            Label(L10n.string(mode.titleKey), systemImage: "checkmark")
                        } else {
                            Text(L10n.string(mode.titleKey))
                        }
                    }
                }
            } label: {
                SettingsMenuValue(text: L10n.string(state.selectedAppearance))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L10n.format("選擇外觀：%@", L10n.string(state.selectedAppearance)))
        }
    }

    private var languageRow: some View {
        AppKeyValueRow(icon: "character.bubble", label: L10n.string("語言"), style: .settings(appSkin)) {
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
            .accessibilityLabel(L10n.format("選擇語言：%@", state.selectedLanguage))
        }
    }

    private var translationLanguageRow: some View {
        SettingsNavigationRow(
            icon: "textformat.abc",
            label: L10n.string("翻譯語言"),
            action: onShowTranslationLanguage
        ) {
            SettingsStatusValue(
                text: "\(state.translationSource) → \(state.translationTarget)",
                color: appSkin.palette.secondaryText
            )
            .accessibilityIdentifier("settings.preferences.translationLanguageValue")
        }
        .accessibilityIdentifier("settings.preferences.translationLanguageRow")
    }

    private var reviewRhythmRow: some View {
        SettingsNavigationRow(
            icon: "timer",
            label: L10n.string("複習節奏"),
            action: onShowReviewSettings
        ) {
            SettingsStatusValue(
                text: state.selectedReviewMode,
                color: appSkin.palette.secondaryText
            )
            .accessibilityIdentifier("settings.preferences.reviewRhythmValue")
        }
        .accessibilityIdentifier("settings.preferences.reviewRhythmRow")
    }

    private var soundFeedbackRow: some View {
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
    }

    private var hapticFeedbackRow: some View {
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
    }

    private var reviewCardLayoutRow: some View {
        SettingsNavigationRow(
            icon: "rectangle.split.2x1",
            label: L10n.string("複習卡片"),
            action: onShowReviewCardLayout,
            accessibilityIdentifier: "settings.preferences.reviewCardLayoutRow"
        ) {
            SettingsStatusValue(
                text: L10n.string(ReviewCardLayoutSummary.titleKey(for: reviewCardLayoutStore.profile)),
                color: appSkin.palette.secondaryText
            )
            .accessibilityIdentifier("settings.preferences.reviewCardLayoutValue")
        }
    }

    private var readerSettingsRow: some View {
        SettingsNavigationRow(
            icon: "textformat.size",
            label: L10n.string("reader.settings.title"),
            action: onShowReaderSettings
        ) {
            SettingsStatusValue(
                text: "\(readerSettings.font.displayName) · \(readerSettings.fontSizeText)",
                color: appSkin.palette.secondaryText
            )
            .accessibilityIdentifier("settings.preferences.readerSettingsValue")
        }
        .accessibilityIdentifier("settings.preferences.readerSettingsRow")
    }

    private var autoSyncRow: some View {
        AppKeyValueRow(
            icon: "arrow.triangle.2.circlepath",
            label: L10n.string("自動同步"),
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

    private var autoLinkRow: some View {
        AppKeyValueRow(
            icon: "point.3.connected.trianglepath.dotted",
            label: L10n.string("自動連結"),
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

    /// 沿用既有兩段 footer 文案（含自動同步說明的組合 key 不拆，保留既有翻譯），
    /// 顯示自動連結 toggle 時追加一句說明。
    private var footerText: String {
        var text = state.showAutoSync
            ? L10n.string("切換後會立即套用到 app 介面。開啟自動同步後，收錄滿 5 個單字會自動同步到雲端。")
            : L10n.string("切換後會立即套用到 app 介面。")
        if state.showAutoLink {
            text += L10n.string("關閉自動連結後，新單字不再自動建立知識圖譜連結；重新開啟會繼續處理累積的單字。")
        }
        return text
    }
}
