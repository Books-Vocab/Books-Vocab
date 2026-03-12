import SwiftUI

struct TranslationLanguageSettingsView: View {
    @Environment(\.vocabSkin) private var vocabSkin

    @Binding var sourceLang: TranslationLanguage
    @Binding var targetLang: TranslationLanguage
    let onChanged: (TranslationLanguage, TranslationLanguage) -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                // Source language section
                VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                    SettingsSectionHeader(title: "閱讀語言", icon: "book")

                    VStack(spacing: 0) {
                        ForEach(Array(TranslationLanguage.sourceLanguages.enumerated()), id: \.element.id) { index, lang in
                            if index > 0 { SettingsDivider() }
                            languageRow(lang, isSelected: lang == sourceLang) {
                                guard sourceLang != lang else { return }
                                sourceLang = lang
                                onChanged(sourceLang, targetLang)
                            }
                        }
                    }
                    .settingsCard()

                    SettingsSectionFooter("書籍的語言".localized)
                }

                // Target language section
                VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                    SettingsSectionHeader(title: "翻譯語言", icon: "character.bubble")

                    VStack(spacing: 0) {
                        ForEach(Array(TranslationLanguage.targetLanguages.enumerated()), id: \.element.id) { index, lang in
                            if index > 0 { SettingsDivider() }
                            languageRow(lang, isSelected: lang == targetLang) {
                                guard targetLang != lang else { return }
                                targetLang = lang
                                onChanged(sourceLang, targetLang)
                            }
                        }
                    }
                    .settingsCard()

                    SettingsSectionFooter("翻譯與解釋會以此語言呈現".localized)
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle("翻譯語言")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func languageRow(
        _ lang: TranslationLanguage,
        isSelected: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            SettingsSelectableRow(isSelected: isSelected) {
                Text(lang.flagEmoji)
                    .font(vocabSkin.typography.body)

                Text(lang.nativeName)
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.primaryText)
            }
        }
        .buttonStyle(.plain)
    }
}

#Preview("Translation Language / Default") {
    AppThemeContainer {
        NavigationStack {
            TranslationLanguageSettingsView(
                sourceLang: .constant(.en),
                targetLang: .constant(.zhHant),
                onChanged: { _, _ in }
            )
        }
    }
}

#Preview("Translation Language / Alt Pair") {
    AppThemeContainer {
        NavigationStack {
            TranslationLanguageSettingsView(
                sourceLang: .constant(.ja),
                targetLang: .constant(.en),
                onChanged: { _, _ in }
            )
        }
    }
}
