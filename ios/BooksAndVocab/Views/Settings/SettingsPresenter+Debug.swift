import SwiftUI

// MARK: - DEBUG Backend Section

// child View struct（原 SettingsPresenter extension function）；不得改回內聯
// — 見 SettingsOtherSection.swift 檔頭的 stack 約束。
#if DEBUG
struct SettingsDebugBackendSection: View {
    @Environment(\.appSkin) var appSkin

    let kg: SettingsPresenterState.KGSection
    let debugLocalServerURL: Binding<String>
    let actions: SettingsPresenterActions

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "DEBUG 後端".localized, icon: "hammer")

            VStack(spacing: 0) {
                if let debug = kg.debug {
                    VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
                        HStack(spacing: AppSpacing.s2) {
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

                        observationPreview(debug.observation)
                    }
                    .padding(appSkin.spacing.cardPadding)
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
                HStack(spacing: AppSpacing.s2) {
                    Image(systemName: systemImage)
                        .font(appSkin.typography.iconSmall)
                    Text(title)
                        .font(appSkin.typography.body.weight(isSelected ? .semibold : .regular))
                }
            }
            .foregroundStyle(isSelected ? appSkin.palette.primaryText : appSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }

    private func observationPreview(_ observation: SettingsPresenterState.KGSection.ObservationSection) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            HStack {
                Text("最近觀測事件".localized)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                Spacer()
                Text(L10n.format("buffer %@", String(observation.totalCount)))
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }

            if observation.previewLines.isEmpty {
                Text("尚未捕捉到 app 端 analytics 事件。".localized)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            } else {
                VStack(alignment: .leading, spacing: AppSpacing.s1) {
                    ForEach(Array(observation.previewLines.enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(appSkin.typography.monoLabel)
                            .foregroundStyle(appSkin.palette.secondaryText)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .lineLimit(2)
                    }
                }
                .padding(appSkin.spacing.cardPadding)
                .background(appSkin.palette.stageBackground)
                .clipShape(RoundedRectangle(cornerRadius: AppShellMetrics.cardCornerRadius, style: .continuous))

                Text("預覽內容已脫敏；完整內容仍以本機 os.Logger 為主。".localized)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
        }
    }
}
#endif
