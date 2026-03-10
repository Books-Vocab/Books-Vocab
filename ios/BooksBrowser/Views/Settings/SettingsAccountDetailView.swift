import SwiftUI

struct SettingsAccountDetailView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let authState: SettingsPresenterState.AuthSection
    let dangerState: SettingsPresenterState.DangerSection?
    let actions: SettingsPresenterActions

    var body: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                accountInfoCard

                if let danger = dangerState {
                    dangerCard(danger)
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle("帳號詳情")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var accountInfoCard: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "帳號資訊", icon: "person.crop.circle")

            VStack(spacing: 0) {
                SettingsRow(icon: "person", label: "名稱") {
                    Text(authState.displayName)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                if let email = authState.email {
                    SettingsDivider()

                    SettingsRow(icon: "envelope", label: "信箱") {
                        Text(email)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                }
            }
            .settingsCard()
        }
    }

    private func dangerCard(_ danger: SettingsPresenterState.DangerSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "危險操作", icon: "exclamationmark.triangle")

            VStack(spacing: 0) {
                Button(role: .destructive, action: actions.requestDeleteAccount) {
                    HStack {
                        Text((danger.isDeletingAccount ? "刪除中..." : "刪除帳號與雲端資料").localized)
                            .font(vocabSkin.typography.body)
                            .foregroundStyle(vocabSkin.palette.destructive)
                        Spacer()
                        Image(systemName: "trash")
                            .font(vocabSkin.typography.iconTiny)
                            .foregroundStyle(vocabSkin.palette.destructive)
                    }
                }
                .buttonStyle(.appAction(.destructive))
                .disabled(danger.isDeletingAccount)
                .accessibilityLabel("刪除帳號與雲端資料")
            }
            .settingsCard()

            SettingsSectionFooter("此操作不可逆，會刪除帳號與所有雲端資料。")
        }
    }
}
