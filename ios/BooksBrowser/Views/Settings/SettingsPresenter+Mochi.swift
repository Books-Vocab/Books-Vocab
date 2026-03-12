import SwiftUI

extension SettingsPresenter {

    // MARK: - Mochi Row

    func mochiRow(_ optionalIntegration: SettingsPresenterState.OptionalIntegrationSection) -> some View {
        SettingsRow(icon: "m.square.fill", label: "Mochi API Key") {
            HStack(spacing: 6) {
                SecureField("可選".localized, text: optionalIntegrationApiKey)
                    .font(vocabSkin.typography.monoLabel)
                    .multilineTextAlignment(.trailing)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .disabled(!optionalIntegration.isEnabled)

                Button(action: actions.showOptionalIntegrationInfo) {
                    Image(systemName: "info.circle")
                        .font(vocabSkin.typography.iconMedium)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - DEBUG Backend Section

    #if DEBUG
    func debugBackendSection(kg: SettingsPresenterState.KGSection, debugLocalServerURL: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "DEBUG 後端".localized, icon: "hammer")

            VStack(spacing: 0) {
                if let debug = kg.debug {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 8) {
                            Button("遠端正式站".localized, action: actions.useProductionBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.quaternaryText : vocabSkin.palette.accent)
                                .accessibilityLabel("切換至遠端正式站".localized)

                            Button("本地開發站".localized, action: actions.useLocalBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.accent : vocabSkin.palette.quaternaryText)
                                .accessibilityLabel("切換至本地開發站".localized)
                        }

                        TextField("本地伺服器 URL".localized, text: debugLocalServerURL)
                            .font(vocabSkin.typography.monoLabel)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)

                        Text(debug.isUsingLocalServer ? "目前使用本地開發站。".localized : "目前使用遠端正式站。".localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                }
            }
            .settingsCard()
        }
    }
    #endif
}
