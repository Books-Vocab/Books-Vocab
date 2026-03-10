import SwiftUI

struct SettingsSubscriptionSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.SubscriptionSection
    let actions: SettingsPresenterActions

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "訂閱", icon: "sparkles.rectangle.stack")

            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                    HStack(alignment: .top, spacing: vocabSkin.spacing.rowContentSpacing) {
                        VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
                            Text(state.planName)
                                .font(vocabSkin.typography.sectionTitle)
                                .foregroundStyle(vocabSkin.palette.primaryText)

                            Text(state.summary)
                                .font(vocabSkin.typography.body)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .lineSpacing(4)
                        }

                        Spacer()

                        subscriptionBadge
                    }

                    Text(state.detail)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)

                    if let pricingUnavailableMessage = state.pricingUnavailableMessage {
                        VocabStateMessageCard(
                            title: "價格載入中",
                            systemImage: "arrow.clockwise.circle",
                            description: pricingUnavailableMessage
                        )
                        .transition(.statusRowReveal)
                    }

                    subscriptionMetaRow(
                        title: "權限來源",
                        value: state.sourceLabel
                    )
                    .transition(.statusRowReveal)

                    if state.isRestoreAvailable {
                        subscriptionMetaRow(
                            title: state.restoreLabel,
                            value: state.restoreDescription,
                            emphasized: true
                        )
                        .transition(.statusRowReveal)
                    }

                    subscriptionMetaRow(
                        title: "管理方式",
                        value: state.managementNote
                    )
                    .transition(.statusRowReveal)

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
                        }
                        .foregroundStyle(vocabSkin.palette.primaryText)
                        .padding(.horizontal, vocabSkin.spacing.controlHorizontalPadding)
                        .padding(.vertical, vocabSkin.spacing.controlVerticalPadding)
                        .background(vocabSkin.palette.pageBackground)
                        .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(state.isRefreshing)
                    .accessibilityLabel(state.ctaTitle)
                }
                .padding(vocabSkin.spacing.cardPadding)
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

    private func subscriptionMetaRow(
        title: String,
        value: String,
        emphasized: Bool = false
    ) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.tinyGap) {
            Text(title)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(emphasized ? vocabSkin.palette.accent : vocabSkin.palette.tertiaryText)

            Text(value)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
