import SwiftUI

struct SettingsSubscriptionSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.SubscriptionSection
    let actions: SettingsPresenterActions

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "訂閱", icon: "sparkles.rectangle.stack")

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
                    }

                    Spacer()

                    subscriptionBadge
                }
                .padding(vocabSkin.spacing.cardPadding)

                SettingsDivider()

                // ── 結構化 meta rows ──
                SettingsRow(icon: "key", label: "權限來源") {
                    Text(state.sourceLabel)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                SettingsDivider()

                SettingsRow(icon: "wrench.and.screwdriver", label: "管理方式") {
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

                    VocabStateMessageCard(
                        title: "價格載入中",
                        systemImage: "arrow.clockwise.circle",
                        description: pricingUnavailableMessage
                    )
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

                        Image(systemName: "chevron.right")
                            .font(vocabSkin.typography.iconSmall)
                            .foregroundStyle(vocabSkin.palette.quaternaryText)
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

            SettingsSectionFooter("Pro 權限由後端統一管理；來源可能是 App Store 訂閱或管理員手動授權。")
        }
    }

    private var subscriptionBadge: some View {
        let tone: Color
        switch state.badgeTone {
        case .neutral:
            tone = vocabSkin.palette.secondaryText
        case .accent:
            tone = vocabSkin.palette.accent
        case .success:
            tone = vocabSkin.palette.success
        }

        return Text(state.badgeText)
            .font(vocabSkin.typography.monoLabel)
            .foregroundStyle(tone)
            .padding(.horizontal, vocabSkin.spacing.badgeHorizontalPadding)
            .padding(.vertical, vocabSkin.spacing.chipVerticalPadding)
            .background(tone.opacity(0.12))
            .clipShape(Capsule())
    }
}
