import SwiftUI

struct SettingsSubscriptionSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.SubscriptionSection
    let actions: SettingsPresenterActions

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "訂閱".localized, icon: "sparkles.rectangle.stack")

            VStack(spacing: 0) {
                // ── 方案標題 + Badge ──
                HStack(alignment: .top, spacing: vocabSkin.spacing.rowContentSpacing) {
                    VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
                        Text(state.planName)
                            .font(vocabSkin.typography.sectionTitle)
                            .foregroundStyle(vocabSkin.palette.primaryText)

                        Text(state.summary)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                            .lineSpacing(3)

                        if !state.detail.isEmpty {
                            Text(state.detail)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                                .lineSpacing(3)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }

                    Spacer()

                    subscriptionBadge
                }
                .padding(vocabSkin.spacing.cardPadding)

                SettingsDivider()

                // ── 結構化 meta rows ──
                SettingsRow(icon: "key", label: "權限來源".localized) {
                    Text(state.sourceLabel)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                SettingsDivider()

                SettingsRow(icon: "wrench.and.screwdriver", label: "管理方式".localized) {
                    Text(state.managementNote)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .multilineTextAlignment(.trailing)
                }

                if state.isRestoreAvailable {
                    SettingsDivider()

                    SettingsRow(icon: "arrow.clockwise", label: state.restoreLabel) {
                        Text(state.restoreDescription)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.accent)
                            .multilineTextAlignment(.trailing)
                    }
                    .transition(.statusRowReveal)
                }

                if let pricingUnavailableMessage = state.pricingUnavailableMessage {
                    SettingsDivider()

                    pricingUnavailableCard(pricingUnavailableMessage)
                        .padding(vocabSkin.spacing.cardPadding)
                        .transition(.statusRowReveal)
                }

                SettingsDivider()

                // ── CTA ──
                Button(action: actions.showSubscriptionPaywall) {
                    HStack(spacing: vocabSkin.spacing.controlGap) {
                        if state.isRefreshing {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: "arrow.right.circle.fill")
                                .font(vocabSkin.typography.iconMedium)
                        }

                        Text(state.ctaTitle)
                            .font(vocabSkin.typography.body.weight(.medium))

                        Spacer()

                        SettingsTrailingChevronIcon()
                    }
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .padding(.horizontal, vocabSkin.spacing.cardPadding)
                    .padding(.vertical, 13)
                    .frame(minHeight: 50)
                }
                .buttonStyle(.plain)
                .disabled(state.isRefreshing)
                .accessibilityLabel(state.ctaTitle)
            }
            .settingsCard()
            .animation(AppMotion.phaseChange, value: state.badgeText)
            .animation(AppMotion.phaseChange, value: state.pricingUnavailableMessage)

            SettingsSectionFooter("Pro 權限由後端統一管理；來源可能是 App Store 訂閱或管理員手動授權。".localized)
        }
    }

    private var subscriptionBadge: some View {
        SettingsStatusBadge(text: state.badgeText, tone: state.badgeTone.color(in: vocabSkin))
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
}
