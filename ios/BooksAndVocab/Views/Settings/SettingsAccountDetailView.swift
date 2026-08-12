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
            .init(icon: "person", label: L10n.string("名稱"), value: authState.displayName)
        ]

        if let email = authState.email, !email.isEmpty {
            items.append(.init(icon: "envelope", label: L10n.string("信箱"), value: email))
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
        .navigationTitle(L10n.string("帳號詳情"))
        .inlineNavigationBarTitle()
        .enableInjection()
    }

    private var dataManagementCard: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("資料管理"), icon: "tray.and.arrow.up")

            VStack(spacing: 0) {
                SettingsNavigationRow(
                    icon: "square.and.arrow.up",
                    label: L10n.string("匯出全部單字 CSV"),
                    action: actions.exportVocabularyCSV
                )
            }
            .settingsCard()

            SettingsSectionFooter(L10n.string("將所有單字本內的單字匯出為 CSV，方便備份或匯入其他工具。"))
        }
        .accessibilityIdentifier("settings.account.dataManagementGroup")
    }

    private var accountInfoCard: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("帳號資訊"), icon: "person.crop.circle")

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
        .accessibilityIdentifier("settings.account.infoGroup")
    }

    private func dangerCard(_ danger: SettingsPresenterState.DangerSection) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("危險操作"), icon: "exclamationmark.triangle")

            VocabStateMessageCard(
                title: danger.isDeletingAccount ? L10n.string("正在刪除帳號") : L10n.string("此操作不可逆"),
                systemImage: danger.isDeletingAccount ? "hourglass" : "exclamationmark.triangle.fill",
                description: danger.isDeletingAccount
                    ? L10n.string("系統正在刪除帳號與雲端資料，完成前請勿關閉 app。")
                    : L10n.string("刪除後會移除帳號與所有雲端資料，且無法復原。")
            )

            VStack(spacing: 0) {
                Button(role: .destructive, action: actions.requestDeleteAccount) {
                    HStack {
                        Text(L10n.string(danger.isDeletingAccount ? "刪除中..." : "刪除帳號與雲端資料"))
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
                .accessibilityLabel(L10n.string("刪除帳號與雲端資料"))
            }
            .settingsCard()

            SettingsSectionFooter(L10n.string("此操作不可逆，會刪除帳號與所有雲端資料。"))
        }
        .accessibilityIdentifier("settings.account.dangerGroup")
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
