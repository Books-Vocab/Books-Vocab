import SwiftUI

extension SettingsPresenter {

    // MARK: - Mochi Row

    func mochiRow(_ optionalIntegration: SettingsPresenterState.OptionalIntegrationSection) -> some View {
        AppKeyValueRow(icon: "m.square.fill", label: "Mochi API Key", style: .settings(vocabSkin)) {
            HStack(spacing: 6) {
                SecureField("可選".localized, text: optionalIntegrationApiKey)
                    .appSettingsTextInputStyle()
                    .disabled(!optionalIntegration.isEnabled)

                SettingsInlineInfoButton(action: actions.showOptionalIntegrationInfo)
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
                    VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                        HStack(spacing: 8) {
                            debugBackendOptionButton(
                                title: "遠端正式站".localized,
                                systemImage: "network",
                                isSelected: !debug.isUsingLocalServer,
                                action: actions.useProductionBackend
                            )

                            debugBackendOptionButton(
                                title: "本地開發站".localized,
                                systemImage: "laptopcomputer",
                                isSelected: debug.isUsingLocalServer,
                                action: actions.useLocalBackend
                            )
                        }

                        SettingsLabeledInputField(title: "本地伺服器 URL".localized) {
                            TextField("本地伺服器 URL".localized, text: debugLocalServerURL)
                                .appSettingsTextInputStyle(alignment: .leading)
                                .submitLabel(.done)
                        }

                        VocabStateMessageCard(
                            title: debug.isUsingLocalServer ? "目前使用本地開發站".localized : "目前使用遠端正式站".localized,
                            systemImage: debug.isUsingLocalServer ? "laptopcomputer" : "network",
                            description: debug.isUsingLocalServer
                                ? "切回正式站前，請確認本地 API 與 app schema 保持同步。".localized
                                : "目前 app 會直接連到正式環境，請避免在這裡做破壞性測試。".localized
                        )
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                }
            }
            .settingsCard()
        }
    }

    private func debugBackendOptionButton(
        title: String,
        systemImage: String,
        isSelected: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            SettingsSelectionTile(isSelected: isSelected) {
                HStack(spacing: 8) {
                    Image(systemName: systemImage)
                        .font(vocabSkin.typography.iconSmall)
                    Text(title)
                        .font(vocabSkin.typography.body.weight(isSelected ? .semibold : .regular))
                }
            }
            .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }
    #endif
}
