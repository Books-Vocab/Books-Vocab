import SwiftUI

struct TranslationLanguageSettingsView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.appTheme) private var appTheme

    @Binding var sourceLang: TranslationLanguage
    @Binding var targetLang: TranslationLanguage
    let onChanged: (TranslationLanguage, TranslationLanguage) async -> Bool

    @State private var savingLanguageID: String? = nil
    @State private var saveError: String? = nil

    var body: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                if let saveError {
                    AppStateMessageCard(
                        title: "儲存失敗".localized,
                        systemImage: "exclamationmark.triangle",
                        description: saveError,
                        style: .themed(appTheme)
                    ) {
                        Button("關閉".localized) {
                            withAnimation(AppMotion.panelState) {
                                self.saveError = nil
                            }
                        }
                        .font(appSkin.typography.caption.weight(.semibold))
                        .foregroundStyle(appTheme.palette.accent)
                    }
                }

                // Source language section
                VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
                    SettingsSectionHeader(title: "閱讀語言", icon: "book")

                    VStack(spacing: 0) {
                        ForEach(Array(TranslationLanguage.sourceLanguages.enumerated()), id: \.element.id) { index, lang in
                            if index > 0 { SettingsDivider() }
                            languageRow(lang, isSelected: lang == sourceLang) {
                                guard sourceLang != lang else { return }
                                let previous = sourceLang
                                sourceLang = lang
                                Task { await commit(source: lang, target: targetLang, savingID: lang.id, rollback: { sourceLang = previous }) }
                            }
                        }
                    }
                    .settingsCard()

                    SettingsSectionFooter("書籍的語言".localized)
                }

                // Target language section
                VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
                    SettingsSectionHeader(title: "翻譯語言", icon: "character.bubble")

                    VStack(spacing: 0) {
                        ForEach(Array(TranslationLanguage.targetLanguages.enumerated()), id: \.element.id) { index, lang in
                            if index > 0 { SettingsDivider() }
                            languageRow(lang, isSelected: lang == targetLang) {
                                guard targetLang != lang else { return }
                                let previous = targetLang
                                targetLang = lang
                                Task { await commit(source: sourceLang, target: lang, savingID: lang.id, rollback: { targetLang = previous }) }
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
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle(L10n.string("翻譯語言"))
        .inlineNavigationBarTitle()
        .enableInjection()
    }

    private func commit(
        source: TranslationLanguage,
        target: TranslationLanguage,
        savingID: String,
        rollback: @escaping () -> Void
    ) async {
        withAnimation(AppMotion.panelState) {
            savingLanguageID = savingID
            saveError = nil
        }
        let ok = await onChanged(source, target)
        withAnimation(AppMotion.panelState) {
            savingLanguageID = nil
            if !ok {
                saveError = "請檢查網路後再試一次".localized
                rollback()
            }
        }
    }

    private func languageRow(
        _ lang: TranslationLanguage,
        isSelected: Bool,
        action: @escaping () -> Void
    ) -> some View {
        let isSaving = savingLanguageID == lang.id
        return Button(action: action) {
            SettingsSelectableRow(isSelected: isSelected) {
                Text(lang.flagEmoji)
                    .font(appSkin.typography.body)

                Text(lang.nativeName)
                    .font(appSkin.typography.body)
                    .foregroundStyle(appSkin.palette.primaryText)

                if isSaving {
                    ProgressView()
                        .controlSize(.small)
                        .tint(appSkin.palette.accent)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(savingLanguageID != nil)
    }
}

#Preview("Translation Language / Default") {
    AppThemeContainer {
        NavigationStack {
            TranslationLanguageSettingsView(
                sourceLang: .constant(.en),
                targetLang: .constant(.zhHant),
                onChanged: { _, _ in true }
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
                onChanged: { _, _ in true }
            )
        }
    }
}

#Preview("Translation Language / Save Failure") {
    AppThemeContainer {
        NavigationStack {
            TranslationLanguageSettingsView(
                sourceLang: .constant(.en),
                targetLang: .constant(.zhHant),
                onChanged: { _, _ in false }
            )
        }
    }
}
