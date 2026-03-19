import SwiftUI

struct SettingsAccountDetailView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let authState: SettingsPresenterState.AuthSection
    let dangerState: SettingsPresenterState.DangerSection?
    let actions: SettingsPresenterActions

    private struct AccountInfoItem: Identifiable {
        let icon: String
        let label: String
        let value: String

        var id: String { label }
    }

    private var accountInfoItems: [AccountInfoItem] {
        var items: [AccountInfoItem] = [
            .init(icon: "person", label: "名稱".localized, value: authState.displayName)
        ]

        if let email = authState.email, !email.isEmpty {
            items.append(.init(icon: "envelope", label: "信箱".localized, value: email))
        }

        return items
    }

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
        .navigationTitle("帳號詳情".localized)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var accountInfoCard: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "帳號資訊".localized, icon: "person.crop.circle")

            VStack(spacing: 0) {
                ForEach(Array(accountInfoItems.enumerated()), id: \.element.id) { index, item in
                    AppKeyValueRow(icon: item.icon, label: item.label, style: .settings(vocabSkin)) {
                        SettingsStatusValue(
                            text: item.value,
                            color: vocabSkin.palette.secondaryText
                        )
                    }

                    if index < accountInfoItems.count - 1 {
                        SettingsDivider()
                    }
                }
            }
            .settingsCard()
        }
    }

    private func dangerCard(_ danger: SettingsPresenterState.DangerSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "危險操作".localized, icon: "exclamationmark.triangle")

            VocabStateMessageCard(
                title: danger.isDeletingAccount ? "正在刪除帳號".localized : "此操作不可逆".localized,
                systemImage: danger.isDeletingAccount ? "hourglass" : "exclamationmark.triangle.fill",
                description: danger.isDeletingAccount
                    ? "系統正在刪除帳號與雲端資料，完成前請勿關閉 app。".localized
                    : "刪除後會移除帳號與所有雲端資料，且無法復原。".localized
            )

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
                .accessibilityLabel("刪除帳號與雲端資料".localized)
            }
            .settingsCard()

            SettingsSectionFooter("此操作不可逆，會刪除帳號與所有雲端資料。".localized)
        }
    }
}

#Preview("Account Detail / Default") {
    AppThemeContainer {
        NavigationStack {
            SettingsAccountDetailView(
                authState: SettingsPresenterPreviewData.subscribedActive.auth,
                dangerState: SettingsPresenterPreviewData.subscribedActive.danger,
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}

#Preview("Account Detail / Deleting") {
    AppThemeContainer {
        NavigationStack {
            SettingsAccountDetailView(
                authState: SettingsPresenterPreviewData.deletingAccount.auth,
                dangerState: SettingsPresenterPreviewData.deletingAccount.danger,
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}
