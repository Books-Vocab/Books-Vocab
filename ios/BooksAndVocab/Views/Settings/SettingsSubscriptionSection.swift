import SwiftUI

struct SettingsSubscriptionSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let state: SettingsPresenterState.SubscriptionSection
    let actions: SettingsPresenterActions

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "訂閱".localized, icon: "sparkles.rectangle.stack")

            VStack(spacing: 0) {
                // ── 方案標題 + Badge ──
                HStack(alignment: .top, spacing: appSkin.spacing.rowContentSpacing) {
                    SettingsSubscriptionInfoBlock(
                        title: state.planName,
                        subtitle: state.summary,
                        detail: state.detail,
                        titleFont: appSkin.typography.sectionTitle
                    )

                    Spacer()

                    subscriptionBadge
                }
                .padding(appSkin.spacing.cardPadding)

                SettingsDivider()

                // ── 結構化 meta rows ──
                AppKeyValueRow(icon: "key", label: "權限來源".localized, style: .settings(appSkin)) {
                    SettingsStatusValue(
                        text: state.sourceLabel,
                        color: appSkin.palette.secondaryText
                    )
                }

                SettingsDivider()

                AppKeyValueRow(icon: "wrench.and.screwdriver", label: "管理方式".localized, style: .settings(appSkin)) {
                    SettingsStatusValue(
                        text: state.managementNote,
                        color: appSkin.palette.secondaryText,
                        lineLimit: 2
                    )
                }

                if state.isRestoreAvailable {
                    SettingsDivider()

                    AppKeyValueRow(icon: "arrow.clockwise", label: state.restoreLabel, style: .settings(appSkin)) {
                        SettingsStatusValue(
                            text: state.restoreDescription,
                            color: appSkin.palette.accent,
                            lineLimit: 2
                        )
                    }
                    .transition(.statusRowReveal)
                }

                if let pricingUnavailableMessage = state.pricingUnavailableMessage {
                    SettingsDivider()

                    pricingUnavailableCard(pricingUnavailableMessage)
                        .padding(appSkin.spacing.cardPadding)
                        .transition(.statusRowReveal)
                }

                SettingsDivider()

                // ── CTA ──
                Button(action: actions.showSubscriptionPaywall) {
                    SettingsActionRowLabel(
                        title: state.ctaTitle,
                        systemImage: "arrow.right.circle.fill",
                        isLoading: state.isRefreshing
                    )
                    // .plain hit-testing falls through the Spacer gap between
                    // the title and the trailing chevron — same dead zone as
                    // SettingsNavigationRow.
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(state.isRefreshing)
                .accessibilityLabel(state.ctaTitle)
            }
            .settingsCard()
            .accessibilityIdentifier(
                state.isActive
                    ? "settings.subscription.pro.active"
                    : "settings.subscription.pro.inactive"
            )
            .animatePhaseChange(state.badgeText)
            .animatePhaseChange(state.pricingUnavailableMessage)

            SettingsSectionFooter("Pro 權限由後端統一管理；來源可能是 App Store 訂閱或管理員手動授權。".localized)
        }
        .enableInjection()
    }

    private var subscriptionBadge: some View {
        SettingsStatusBadge(text: state.badgeText, tone: state.badgeTone.color(in: appSkin))
    }

    private func pricingUnavailableCard(_ message: String) -> some View {
        VocabStateMessageCard(
            title: state.isRefreshing ? "價格載入中".localized : "價格稍後更新".localized,
            systemImage: state.isRefreshing ? "arrow.clockwise.circle" : "info.circle",
            description: message
        )
    }
}

#Preview("Subscription / Active") {
    AppThemeContainer {
        ScrollView {
            SettingsSubscriptionSection(
                state: SettingsPresenterPreviewData.subscribedActive.subscription!,
                actions: SettingsPresenterPreviewData.noopActions
            )
            .padding()
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Subscription / Pricing Unavailable") {
    AppThemeContainer {
        ScrollView {
            SettingsSubscriptionSection(
                state: SettingsPresenterPreviewData.pricingUnavailable.subscription!,
                actions: SettingsPresenterPreviewData.noopActions
            )
            .padding()
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}
