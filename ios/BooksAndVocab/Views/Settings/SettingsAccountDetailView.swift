import SwiftUI

struct SettingsAccountDetailView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
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

                if authState.isLoggedIn {
                    dataManagementCard
                }

                if let danger = dangerState {
                    dangerCard(danger)
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle("帳號詳情".localized)
        .inlineNavigationBarTitle()
        .enableInjection()
    }

    private var dataManagementCard: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "資料管理".localized, icon: "tray.and.arrow.up")

            VStack(spacing: 0) {
                SettingsNavigationRow(
                    icon: "square.and.arrow.up",
                    label: "匯出全部單字 CSV".localized,
                    action: actions.exportVocabularyCSV
                )
            }
            .settingsCard()

            SettingsSectionFooter("將所有單字本內的單字匯出為 CSV，方便備份或匯入其他工具。".localized)
        }
    }

    private var accountInfoCard: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "帳號資訊".localized, icon: "person.crop.circle")

            VStack(spacing: 0) {
                ForEach(Array(accountInfoItems.enumerated()), id: \.element.id) { index, item in
                    AppKeyValueRow(icon: item.icon, label: item.label, style: .settings(appSkin)) {
                        SettingsStatusValue(
                            text: item.value,
                            color: appSkin.palette.secondaryText
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
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
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
                            .font(appSkin.typography.body)
                            .foregroundStyle(appSkin.palette.destructive)
                        Spacer()
                        Image(systemName: "trash")
                            .font(appSkin.typography.iconTiny)
                            .foregroundStyle(appSkin.palette.destructive)
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
    .environmentObject(AppAppearanceStore.preview)
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
    .environmentObject(AppAppearanceStore.preview)
}
