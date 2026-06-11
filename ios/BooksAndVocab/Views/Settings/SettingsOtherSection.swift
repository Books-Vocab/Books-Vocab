//
//  SettingsOtherSection.swift
//  Books & Vocab
//
//  「其他」區塊。必須是獨立 child View struct，不得改回 SettingsPresenter 的
//  computed property：section 樹會整段內聯進 body.getter 的單一 stack frame
//  鏈（Debug build 無最佳化），真機 main thread stack 僅 1MB，曾因此 stack
//  overflow（2026-06-11，___chkstk_darwin + KERN_PROTECTION_FAILURE 定讞）。
//  child struct 的 body 由 SwiftUI 另行求值，不疊在父 frame 上。
//

import SwiftUI

struct SettingsOtherSection: View {
    @Environment(\.appTheme) var appTheme
    @Environment(\.appSkin) var appSkin
    @Environment(\.quotaStore) var quotaStore

    struct ExternalActionItem: Identifiable {
        let icon: String
        let label: String
        let action: () -> Void

        var id: String { label }
    }

    let syncSummary: SettingsPresenterState.SyncSummaryState?
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
            SettingsSectionHeader(title: "其他".localized, icon: "ellipsis.circle")

            VStack(spacing: 0) {
                // 同步狀態 (only when logged in)
                if let syncSummary {
                    syncSummaryRow(syncSummary)
                    SettingsDivider()
                }

                // 今日額度 (always when logged in)
                if isLoggedIn {
                    quotaRow
                    SettingsDivider()
                }

                ForEach(Array(externalActionItems.enumerated()), id: \.element.id) { index, item in
                    externalActionRow(item)

                    if index < externalActionItems.count - 1 {
                        SettingsDivider()
                    }
                }
            }
            .settingsCard()

            // Version footer
            Text("\("版本".localized) \(version)")
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
                .frame(maxWidth: .infinity)
                .padding(.top, appSkin.spacing.tinyGap)
        }
    }

    // MARK: - Sync Summary Row

    private func syncSummaryRow(_ summary: SettingsPresenterState.SyncSummaryState) -> some View {
        Button {
            actions.resync()
        } label: {
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
            .appHoverRowTint()
            // .plain hit-testing falls through the Spacer gap inside
            // AppKeyValueRow — same dead zone as SettingsNavigationRow.
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(summary.isSyncing)
    }

    private func externalActionRow(_ item: ExternalActionItem) -> some View {
        SettingsNavigationRow(
            icon: item.icon,
            label: item.label.localized,
            action: item.action
        )
    }
}
