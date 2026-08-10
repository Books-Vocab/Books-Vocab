//
//  SettingsOtherSection.swift
//  Books & Vocab
//
//  「其他」section（同步狀態 / 今日額度 / 外部連結 / 版本 footer）。
//
//  獨立 View struct 不是風格選擇，是真機 stack 預算約束：iOS main thread
//  stack 只有 1MB，Debug -Onone 下 SwiftUI 巨型泛型 frame 不會被優化掉。
//  本 section 原本是 SettingsPresenter 的 computed property，整棵樹 inline
//  進 body 單次求值，光 otherSection 鏈就吃掉 ~150KB、並把 ScrollView/VStack
//  的 content 泛型撐成 255KB/113KB frame，設定 sheet 一開就 stack overflow
//  （EXC_BAD_ACCESS code=2 撞 guard page；取證 dump 2026-06-11）。拆成
//  struct 後 body 只構造小型 struct 值，子樹由 SwiftUI 另一輪 attribute
//  update 求值，單一 frame 不再揹整棵樹。Simulator main thread 是 8MB，
//  永遠測不出這條——不要因為 sim 沒事就把 section 收回 computed property。
//

import SwiftUI

struct SettingsOtherSection: View {
    @Environment(\.appTheme) var appTheme
    @Environment(\.appSkin) var appSkin
    @Environment(\.quotaStore) var quotaStore
    /// 高頻 observable 隔離在葉節點讀取（`PodcastProgressTicker` 模式）：同步一輪
    /// 會寫進 store 幾十次，讓它只驅動這一小塊，不讓整個設定頁跟著重算。
    @Environment(\.syncProgressStore) var syncProgress

    private struct ExternalActionItem: Identifiable {
        let icon: String
        let label: String
        let action: () -> Void

        var id: String { label }
    }

    let syncSummary: SettingsPresenterState.SyncSummaryState?
    let bookSync: SettingsPresenterState.BookSyncState?
    let isLoggedIn: Bool
    let version: String
    let actions: SettingsPresenterActions

    @State private var syncRotation: Double = 0

    private var externalActionItems: [ExternalActionItem] {
        [
            .init(icon: "hand.raised", label: "隱私政策", action: actions.openPrivacyPolicy),
            .init(icon: "doc.text", label: "服務條款", action: actions.openTermsOfService),
            .init(icon: "questionmark.circle", label: "支援", action: actions.openSupport),
            .init(icon: "star", label: "為 App 評分", action: actions.requestAppRating)
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            if hasSyncGroup {
                syncGroup
            }

            externalActionsGroup

            // Version footer
            Text("\("版本".localized) \(version)")
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
                .frame(maxWidth: .infinity)
                .padding(.top, appSkin.spacing.tinyGap)
        }
    }

    private var hasSyncGroup: Bool {
        syncSummary != nil || bookSync != nil || isLoggedIn
    }

    private var syncGroup: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(
                title: L10n.string("雲端同步與跨裝置狀態"),
                icon: "arrow.triangle.2.circlepath"
            )

            VStack(spacing: 0) {
                if let syncSummary {
                    syncSummaryRow(syncSummary)
                    if bookSync != nil || isLoggedIn {
                        SettingsDivider()
                    }
                }

                if let bookSync {
                    bookSyncRow(bookSync)
                    if isLoggedIn {
                        SettingsDivider()
                    }
                }

                if isLoggedIn {
                    quotaRow
                }
            }
            .settingsCard()
        }
        .accessibilityIdentifier("settings.other.syncGroup")
    }

    private var externalActionsGroup: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("其他"), icon: "ellipsis.circle")

            VStack(spacing: 0) {
                ForEach(Array(externalActionItems.enumerated()), id: \.element.id) { index, item in
                    externalActionRow(item)

                    if index < externalActionItems.count - 1 {
                        SettingsDivider()
                    }
                }
            }
            .settingsCard()
        }
        .accessibilityIdentifier("settings.other.externalActionsGroup")
    }

    // MARK: - Sync Summary Row

    private func syncSummaryRow(_ summary: SettingsPresenterState.SyncSummaryState) -> some View {
        let progressPanelIsVisible = SettingsSyncProgressPanel.isVisible(
            isSyncing: summary.isSyncing,
            steps: syncProgress.steps
        )

        return VStack(spacing: 0) {
            syncSummaryButton(summary)

            // 逐步清單 + 進度條。放在 Button **外面**：它有自己的無障礙語意，
            // 而且整段同步期間 Button 是 disabled 的，包進去等於把一個活的進度
            // 顯示塞進一個死的控制項裡。
            if progressPanelIsVisible {
                SettingsSyncProgressPanel(
                    steps: syncProgress.steps,
                    fraction: syncProgress.fraction
                )
                .transition(.statusRowReveal)
            }
        }
        // 展開與收合共用這一條。收合時 `lastSyncedText` 那一行同時淡回來
        // （它本來就以 `isSyncing` 為條件），所以整段是一次過渡而不是兩段接力。
        // The phase key must include the declared-step identity. On start,
        // `isSyncing` becomes true before `begin` publishes `steps`; observing
        // only the former makes insertion happen without a transition.
        .animation(AppMotion.phaseChange, value: progressPanelIsVisible)
    }

    private func syncSummaryButton(_ summary: SettingsPresenterState.SyncSummaryState) -> some View {
        Button {
            actions.resync()
        } label: {
            // Two lines, matching bookSyncRow: the trailing slot is a single
            // truncating line, so the last-sync time gets its own caption row
            // instead of being the third `·` segment that always fell off.
            VStack(spacing: 0) {
                AppKeyValueRow(
                    icon: "arrow.triangle.2.circlepath",
                    label: "同步狀態".localized,
                    style: .settings(appSkin)
                ) {
                    if summary.isSyncing {
                        HStack(spacing: appSkin.spacing.inlineGap) {
                            Image(systemName: "arrow.triangle.2.circlepath")
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.accent)
                                .rotationEffect(.degrees(syncRotation))
                                .onAppear {
                                    withAnimation(AppMotion.breathing) {
                                        syncRotation = 360
                                    }
                                }
                                .onDisappear { syncRotation = 0 }
                            Text("同步中…".localized)
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.secondaryText)
                        }
                    } else {
                        SettingsStatusSummaryValue(
                            text: summary.summaryText,
                            color: summary.isConnected ? appSkin.palette.success : appTheme.palette.warning
                        )
                    }
                }

                // Omitted entirely when this device has never completed a sync —
                // better a missing line than a fabricated time.
                if let lastSyncedText = summary.lastSyncedText, !summary.isSyncing {
                    Text(lastSyncedText)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .lineLimit(1)
                        .padding(.horizontal, appSkin.spacing.cardPadding)
                        .padding(.bottom, appSkin.spacing.tinyGap)
                }
            }
            .appHoverRowTint()
            // .plain hit-testing falls through the Spacer gap inside
            // AppKeyValueRow — same dead zone as SettingsNavigationRow.
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(summary.isSyncing)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("settings.syncSummary")
    }

    // MARK: - iCloud 書庫同步列

    private func bookSyncRow(_ sync: SettingsPresenterState.BookSyncState) -> some View {
        VStack(spacing: 0) {
            AppKeyValueRow(
                icon: "icloud",
                label: "iCloud 書庫".localized,
                style: .settings(appSkin)
            ) {
                SettingsStatusSummaryValue(
                    text: sync.text,
                    color: bookSyncColor(sync.tone)
                )
            }

            if let detail = sync.detail {
                Text(detail)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appTheme.palette.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineLimit(3)
                    .padding(.horizontal, appSkin.spacing.cardPadding)
                    .padding(.bottom, appSkin.spacing.tinyGap)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("settings.bookSync")
    }

    private func bookSyncColor(_ tone: SettingsPresenterState.BookSyncState.Tone) -> Color {
        switch tone {
        case .progress: return appSkin.palette.secondaryText
        case .success:  return appSkin.palette.success
        case .warning:  return appTheme.palette.warning
        }
    }

    private func externalActionRow(_ item: ExternalActionItem) -> some View {
        SettingsNavigationRow(
            icon: item.icon,
            label: item.label.localized,
            action: item.action
        )
    }

    // MARK: - Quota Row

    private var quotaRow: some View {
        VStack(spacing: 0) {
            AppKeyValueRow(icon: "gauge.with.dots.needle.bottom.50percent", label: "今日額度".localized, style: .settings(appSkin)) {
                SettingsStatusValue(
                    text: quotaStore.isExhausted
                        ? quotaStore.resetText
                        : "\(Int(quotaStore.fraction * 100))%",
                    color: quotaTextColor
                )
            }

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    AppRoundedRect(roundness: AppRoundness.pill)
                        .fill(quotaBarColor.opacity(0.15))

                    AppRoundedRect(roundness: AppRoundness.pill)
                        .fill(quotaBarColor)
                        .frame(width: geo.size.width * quotaStore.fraction)
                        .animateSpring(quotaStore.fraction)
                }
            }
            .frame(height: 3)
            .padding(.horizontal, appSkin.spacing.cardPadding)
            .padding(.bottom, appSkin.spacing.tinyGap)
        }
    }

    private var quotaBarColor: Color {
        switch quotaStore.level {
        case .normal:    return appSkin.palette.success
        case .warning:   return appTheme.palette.warning
        case .critical:  return appSkin.palette.destructive
        case .exhausted: return appSkin.palette.destructive
        }
    }

    private var quotaTextColor: Color {
        switch quotaStore.level {
        case .normal:    return appSkin.palette.secondaryText
        case .warning:   return appTheme.palette.warning
        case .critical:  return appSkin.palette.destructive
        case .exhausted: return appSkin.palette.destructive
        }
    }
}
