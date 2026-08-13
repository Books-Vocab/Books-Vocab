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
        .accessibilityIdentifier("settings.account.scrollView")
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle(L10n.string("帳號詳情"))
        .inlineNavigationBarTitle()
        .settingsDetailNavigationBackButton()
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
        .accessibilityElement(children: .contain)
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
                            color: appSkin.palette.secondaryText,
                            lineLimit: nil
                        )
                        .fixedSize(horizontal: false, vertical: true)
                        .layoutPriority(1)
                        .accessibilityIdentifier(index == 0 ? "settings.account.info.name" : "settings.account.info.email")
                    }

                    if index < accountInfoItems.count - 1 {
                        SettingsDivider()
                    }
                }
            }
            .settingsCard()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.account.infoGroup")
    }

    private func dangerCard(_ danger: SettingsPresenterState.DangerSection) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("危險操作"), icon: "exclamationmark.triangle")

            if let resetLifecycle = danger.resetLifecycle {
                resetBoundaryCard(resetLifecycle)
            }

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
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.account.dangerGroup")
    }

    private func resetBoundaryCard(_ lifecycle: SettingsResetLifecycle) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            HStack(spacing: appSkin.spacing.controlGap) {
                Image(systemName: resetSystemImage(for: lifecycle.phase))
                    .font(appSkin.typography.iconMedium)
                    .foregroundStyle(resetTone(for: lifecycle.phase))

                Text(resetPhaseTitle(for: lifecycle.phase))
                    .font(appSkin.typography.body.weight(.semibold))
                    .foregroundStyle(appSkin.palette.primaryText)
                    .accessibilityIdentifier("settings.account.resetBoundary.phase")
                    .accessibilityValue(lifecycle.phase.rawValue)

                Spacer()
            }

            if let terminalMessage = lifecycle.terminalMessage {
                Text(terminalMessage)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("settings.account.resetBoundary.message")
            } else {
                Text(resetDescription(for: lifecycle.phase))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(alignment: .leading, spacing: 0) {
                resetSnapshotSection(
                    title: L10n.string("重設前"),
                    snapshot: lifecycle.before,
                    identifier: "settings.account.resetBoundary.before"
                )
                SettingsDivider(leadingInset: 0)
                resetSnapshotSection(
                    title: L10n.string("完成後"),
                    snapshot: lifecycle.after,
                    identifier: "settings.account.resetBoundary.after"
                )
            }
            .settingsCard()

            Button(action: actions.resetLocalData) {
                HStack {
                    Text(resetActionTitle(for: lifecycle.phase))
                        .font(appSkin.typography.body)
                    Spacer()
                    if lifecycle.phase == .resetting {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: lifecycle.phase == .failed ? "arrow.clockwise" : "arrow.counterclockwise")
                            .font(appSkin.typography.iconTiny)
                    }
                }
                .foregroundStyle(lifecycle.canRetry ? appSkin.palette.destructive : appSkin.palette.tertiaryText)
            }
            .buttonStyle(.appAction(.destructive))
            .disabled(!lifecycle.canRetry || lifecycle.phase == .resetting)
            .accessibilityIdentifier("settings.account.resetBoundary.resetButton")
            .accessibilityLabel(resetActionTitle(for: lifecycle.phase))
        }
        .padding(appSkin.spacing.cardPadding)
        .background(appSkin.palette.cardBackground)
        .clipShape(AppRoundedRect(roundness: AppRoundness.card))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.account.resetBoundary")
    }

    private func resetSnapshotSection(
        title: String,
        snapshot: SettingsResetLifecycle.Snapshot,
        identifier: String
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(appSkin.typography.caption.weight(.semibold))
                .foregroundStyle(appSkin.palette.secondaryText)
                .padding(.horizontal, appSkin.spacing.cardPadding)
                .padding(.top, appSkin.spacing.rowMicroGap)

            AppKeyValueRow(icon: "square.stack.3d.up", label: L10n.string("本機單字"), style: .settings(appSkin)) {
                let cardCountText = snapshot.localCardCount.map { L10n.format("%@ 張", "\($0)") }
                    ?? L10n.string("無法讀取")
                Text(cardCountText)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .lineLimit(1)
                    .multilineTextAlignment(.trailing)
                .accessibilityIdentifier("\(identifier).localCardCount")
                .accessibilityLabel(cardCountText)
                .accessibilityValue(snapshot.localCardCountError ?? "")
            }
            AppKeyValueRow(icon: "slider.horizontal.3", label: L10n.string("設定偏好"), style: .settings(appSkin)) {
                let preferencesText = snapshot.hasCustomPreferences ? L10n.string("已自訂") : L10n.string("預設值")
                Text(preferencesText)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .lineLimit(1)
                    .multilineTextAlignment(.trailing)
                .accessibilityIdentifier("\(identifier).preferences")
                .accessibilityLabel(preferencesText)
            }
            AppKeyValueRow(icon: "person.crop.circle", label: L10n.string("登入狀態"), style: .settings(appSkin)) {
                let loginStatusText = snapshot.isLoggedIn ? L10n.string("已登入") : L10n.string("未登入")
                Text(loginStatusText)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .lineLimit(1)
                    .multilineTextAlignment(.trailing)
                .accessibilityIdentifier("\(identifier).loginStatus")
                .accessibilityLabel(loginStatusText)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
    }

    private func resetPhaseTitle(for phase: SettingsResetLifecycle.Phase) -> String {
        switch phase {
        case .preReset: return L10n.string("準備重設本機資料")
        case .resetting: return L10n.string("正在重設本機資料")
        case .succeeded: return L10n.string("本機資料已重設")
        case .failed: return L10n.string("重設本機資料失敗")
        }
    }

    private func resetDescription(for phase: SettingsResetLifecycle.Phase) -> String {
        switch phase {
        case .preReset:
            return L10n.string("這會清除本機單字與設定偏好，但保留目前登入帳號。")
        case .resetting:
            return L10n.string("正在清除本機資料，完成前請勿關閉 app。")
        case .succeeded:
            return L10n.string("本機資料與設定已回到預設狀態。")
        case .failed:
            return L10n.string("本機資料尚未清除，請重試。")
        }
    }

    private func resetActionTitle(for phase: SettingsResetLifecycle.Phase) -> String {
        phase == .failed ? L10n.string("重試本機資料重設") : L10n.string("重設本機資料")
    }

    private func resetSystemImage(for phase: SettingsResetLifecycle.Phase) -> String {
        switch phase {
        case .preReset: return "exclamationmark.triangle"
        case .resetting: return "hourglass"
        case .succeeded: return "checkmark.circle"
        case .failed: return "xmark.circle"
        }
    }

    private func resetTone(for phase: SettingsResetLifecycle.Phase) -> Color {
        switch phase {
        case .preReset, .failed: return appSkin.palette.destructive
        case .resetting: return appSkin.palette.secondaryText
        case .succeeded: return appSkin.palette.success
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
