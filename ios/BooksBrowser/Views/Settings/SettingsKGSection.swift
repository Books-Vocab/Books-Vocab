import SwiftUI

struct SettingsKGSection: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.KGSection
    let debugLocalServerURL: Binding<String>?
    let actions: SettingsPresenterActions

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "Knowledge Graph", icon: "brain.head.profile")

            VStack(spacing: 0) {
                SettingsRow(icon: "server.rack", label: "伺服器") {
                    Text(state.serverURL)
                        .font(vocabSkin.typography.monoLabel)
                        .multilineTextAlignment(.trailing)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                SettingsDivider()

                SettingsRow(icon: "antenna.radiowaves.left.and.right", label: "連線狀態") {
                    HStack(spacing: 8) {
                        let statusTone = state.isConnected ? vocabSkin.palette.success : appTheme.palette.warning
                        Circle()
                            .fill(statusTone)
                            .frame(width: 8, height: 8)
                            .shadow(
                                color: statusTone.opacity(0.6),
                                radius: state.connectionPulse ? 5 : 2
                            )
                        Text((state.isConnected ? "已連線" : "離線").localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                }

                if state.isConnected {
                    SettingsDivider()

                    SettingsRow(icon: "text.book.closed", label: "字庫卡片") {
                        Text(L10n.format("%@ 張", "\(state.serverCardCount)"))
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                    .transition(.statusRowReveal)

                    if let lastSyncDescription = state.lastSyncDescription {
                        SettingsDivider()

                        SettingsRow(icon: "arrow.clockwise", label: "最後同步") {
                            Text(lastSyncDescription)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                        .transition(.statusRowReveal)
                    }
                }

#if DEBUG
                if let debug = state.debug, let debugLocalServerURL {
                    SettingsDivider()

                    VStack(alignment: .leading, spacing: 12) {
                        Text("DEBUG 後端")
                            .font(vocabSkin.typography.captionStrong)
                            .foregroundStyle(vocabSkin.palette.secondaryText)

                        HStack(spacing: 8) {
                            Button("遠端正式站", action: actions.useProductionBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.quaternaryText : vocabSkin.palette.accent)

                            Button("本地開發站", action: actions.useLocalBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.accent : vocabSkin.palette.quaternaryText)
                        }

                        TextField("本地伺服器 URL", text: debugLocalServerURL)
                            .font(vocabSkin.typography.monoLabel)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)

                        Text(debug.isUsingLocalServer ? "目前使用本地開發站。" : "目前使用遠端正式站。")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                }
#endif
            }
            .settingsCard()
            .animation(AppMotion.emphasizedSpring, value: state.isConnected)
            .animation(AppMotion.emphasizedSpring, value: state.serverCardCount)

            SettingsSectionFooter("KG 伺服器負責生詞 AI 增強、知識連結與可選的第三方整合。")
        }
    }
}
