import SwiftUI

struct SettingsAccountSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.AuthSection
    let subscription: SettingsPresenterState.SubscriptionSection?
    let manualLoginUserId: Binding<String>?
    let actions: SettingsPresenterActions
    var onShowAccountDetail: (() -> Void)?
    var onShowSubscriptionDetail: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "帳號".localized, icon: "person.crop.circle")

            VStack(spacing: 0) {
                if state.isLoggedIn {
                    loggedInView
                        .transition(.modalSwap)
                } else {
                    loginView
                        .transition(.modalSwap)
                }
            }
            .settingsCard()
            .overlay {
                if state.isAuthenticating {
                    ZStack {
                        RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                            .fill(vocabSkin.palette.pageBackground.opacity(0.85))
                        VStack(spacing: vocabSkin.spacing.controlGap) {
                            ProgressView()
                                .controlSize(.regular)
                            Text("正在驗證帳號…".localized)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                    }
                    .transition(.contentSwap)
                }
            }
            .animation(AppMotion.phaseChange, value: state.isAuthenticating)
            .animation(AppMotion.modalSwapSpring, value: state.isLoggedIn)
        }
    }

    private var loginView: some View {
        VStack(spacing: 0) {
            VStack(spacing: AccountMetrics.authHeroSpacing) {
                Image("AppIconImage")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 64, height: 64)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .opacity(state.iconBreathing ? 0.85 : 1.0)
                    .animation(AppMotion.breathing, value: state.iconBreathing)

                VStack(spacing: AccountMetrics.authCopySpacing) {
                    Text("解鎖完整功能".localized)
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Text("AI 翻譯・知識圖譜・雲端同步".localized)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }
            }
            .padding(.vertical, AccountMetrics.authHeroVerticalPadding)
            .frame(maxWidth: .infinity)

            SettingsDivider(leadingInset: 0)

            VStack(spacing: AccountMetrics.authActionSpacing) {
                Button(action: actions.loginWithGoogle) {
                    SettingsAuthButton(title: "以 Google 繼續") {
                        SettingsSocialBadge(kind: .google)
                    }
                }
                .buttonStyle(.plain)
                .appSettingsButtonChrome()
                .accessibilityLabel("使用 Google 帳號登入".localized)

                Button(action: actions.loginWithApple) {
                    SettingsAuthButton(title: "以 Apple 繼續") {
                        SettingsSocialBadge(kind: .apple)
                    }
                }
                .buttonStyle(.plain)
                .appSettingsButtonChrome()
                .accessibilityLabel("使用 Apple 帳號登入".localized)

#if DEBUG
                if let manualLoginUserId, let debug = state.debug {
                    SettingsDivider(leadingInset: 0)
                        .padding(.vertical, AppMetrics.spacingSmall)

                    HStack(spacing: 8) {
                        TextField("帳號 ID（手動）".localized, text: manualLoginUserId)
                            .font(vocabSkin.typography.monoLabel)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)

                        Button("登入".localized, action: actions.manualLogin)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .accessibilityLabel("開發者登入".localized)
                    }

                    if let manualLoginHint = debug.manualLoginHint, !manualLoginHint.isEmpty {
                        Text(manualLoginHint)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
#endif

                if let error = state.authError {
                    VocabStateMessageCard(
                        title: "登入暫時失敗".localized,
                        systemImage: "exclamationmark.triangle.fill",
                        description: error
                    )
                    .padding(.top, vocabSkin.spacing.microGap)
                }
            }
            .padding(.horizontal, AccountMetrics.authBlockPadding)
            .padding(.vertical, AccountMetrics.authBlockPadding)
        }
    }

    private var loggedInView: some View {
        VStack(spacing: 0) {
            // Account info — tappable to show account detail
            Button {
                onShowAccountDetail?()
            } label: {
                HStack {
                    SettingsAuthSummary(state: state)
                    SettingsTrailingChevronIcon()
                }
                .padding(vocabSkin.spacing.cardPadding)
            }
            .buttonStyle(.plain)

            // Subscription summary row
            if let subscription {
                SettingsDivider(leadingInset: 0)

                Button {
                    if subscription.isActive {
                        onShowSubscriptionDetail?()
                    } else {
                        actions.showSubscriptionPaywall()
                    }
                } label: {
                    HStack(spacing: vocabSkin.spacing.controlGap) {
                        Image(systemName: subscription.isActive
                              ? "checkmark.seal.fill"
                              : "sparkles.rectangle.stack")
                            .font(vocabSkin.typography.iconMedium)
                            .foregroundStyle(subscription.isActive
                                             ? vocabSkin.palette.success
                                             : vocabSkin.palette.accent)

                        VStack(alignment: .leading, spacing: 2) {
                            Text(subscriptionRowTitle(for: subscription))
                                .font(vocabSkin.typography.body.weight(.medium))
                                .foregroundStyle(vocabSkin.palette.primaryText)
                            Text(subscriptionRowSubtitle(for: subscription))
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .lineLimit(2)
                        }

                        Spacer()

                        if subscription.isActive {
                            subscriptionBadge(subscription)
                        } else {
                            SettingsStatusBadge(
                                text: "升級".localized,
                                tone: vocabSkin.palette.accent
                            )
                        }

                        SettingsTrailingChevronIcon()
                    }
                    .padding(.horizontal, vocabSkin.spacing.cardPadding)
                    .padding(.vertical, 13)
                }
                .buttonStyle(.plain)
            }

            SettingsDivider(leadingInset: 0)

            // Logout button
            Button(role: .destructive, action: actions.logout) {
                Text("登出帳號".localized)
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.destructive)
            }
            .buttonStyle(.appAction(.destructive))
            .padding(vocabSkin.spacing.cardPadding)
            .accessibilityLabel("登出帳號".localized)
        }
    }

    private func subscriptionBadge(_ sub: SettingsPresenterState.SubscriptionSection) -> some View {
        SettingsStatusBadge(text: sub.badgeText, tone: sub.badgeTone.color(in: vocabSkin))
    }

    private func subscriptionRowTitle(for subscription: SettingsPresenterState.SubscriptionSection) -> String {
        subscription.isActive ? "Pro 已啟用".localized : subscription.planName
    }

    private func subscriptionRowSubtitle(for subscription: SettingsPresenterState.SubscriptionSection) -> String {
        if subscription.isActive {
            return subscription.summary.isEmpty ? subscription.detail : subscription.summary
        }
        if let pricingUnavailableMessage = subscription.pricingUnavailableMessage, !pricingUnavailableMessage.isEmpty {
            return pricingUnavailableMessage
        }
        return subscription.summary
    }
}

// MARK: - Private Helpers

private enum AccountMetrics {
    static let authHeroSpacing: CGFloat = 10
    static let authCopySpacing: CGFloat = 4
    static let authActionSpacing: CGFloat = 10
    static let authHeroVerticalPadding: CGFloat = 24
    static let authBlockPadding: CGFloat = 16
    static let authButtonSpacing: CGFloat = 12
    static let authRowSpacing: CGFloat = 14
    static let authStatusSpacing: CGFloat = 6
    static let authAvatarSize: CGFloat = 46
    static let authSocialBadgeSize: CGFloat = 22
    static let authSocialShadowRadius: CGFloat = AppShadows.controlRadius
    static let authSocialShadowY: CGFloat = AppShadows.controlY
}

private enum SettingsSocialKind {
    case google
    case apple
}

private struct SettingsSocialBadge: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let kind: SettingsSocialKind

    var body: some View {
        ZStack {
            Circle()
                .fill(backgroundColor)
                .frame(
                    width: AccountMetrics.authSocialBadgeSize,
                    height: AccountMetrics.authSocialBadgeSize
                )
                .shadow(
                    color: shadowColor,
                    radius: AccountMetrics.authSocialShadowRadius,
                    y: AccountMetrics.authSocialShadowY
                )

            Group {
                switch kind {
                case .google:
                    Text("G")
                        .font(vocabSkin.typography.captionStrong)
                        .foregroundStyle(AppBrandColors.googleRed)
                case .apple:
                    Image(systemName: "apple.logo")
                        .font(vocabSkin.typography.iconTiny)
                        .foregroundStyle(vocabSkin.palette.pageBackground)
                }
            }
        }
    }

    private var backgroundColor: Color {
        switch kind {
        case .google:
            return vocabSkin.palette.cardBackground
        case .apple:
            return AppBrandColors.appleBlack
        }
    }

    private var shadowColor: Color {
        switch kind {
        case .google:
            return vocabSkin.palette.shadow.opacity(0.9)
        case .apple:
            return .clear
        }
    }
}

private struct SettingsAuthButton<Leading: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    @ViewBuilder let leading: Leading

    var body: some View {
        HStack(spacing: AccountMetrics.authButtonSpacing) {
            leading

            Text(title.localized)
                .font(vocabSkin.typography.body.weight(.medium))

            Spacer()

            SettingsTrailingChevronIcon()
        }
    }
}

struct SettingsAuthSummary: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.AuthSection

    var body: some View {
        HStack(spacing: AccountMetrics.authRowSpacing) {
            avatar

            VStack(alignment: .leading, spacing: 3) {
                Text(state.displayName)
                    .font(vocabSkin.typography.sectionTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .lineLimit(1)

                if let email = state.email {
                    Text(email)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineLimit(1)
                }
            }

            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(vocabSkin.typography.symbolLarge)
                .foregroundStyle(vocabSkin.palette.success)
                .symbolEffect(.bounce, value: state.isLoggedIn)
        }
    }

    @ViewBuilder
    private var avatar: some View {
        ZStack {
            Circle()
                .fill(vocabSkin.palette.mutedFill)
                .frame(
                    width: AccountMetrics.authAvatarSize,
                    height: AccountMetrics.authAvatarSize
                )

            if let avatarURL = state.avatarURL {
                AsyncImage(url: avatarURL) { image in
                    image.resizable().scaledToFill()
                } placeholder: {
                    Image(systemName: "person.fill")
                        .font(vocabSkin.typography.symbolLarge)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }
                .frame(
                    width: AccountMetrics.authAvatarSize,
                    height: AccountMetrics.authAvatarSize
                )
                .clipShape(Circle())
            } else if let initials = state.userInitials {
                Text(initials)
                    .font(vocabSkin.typography.sectionTitle)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
            } else {
                Image(systemName: "person.fill")
                    .font(vocabSkin.typography.symbolLarge)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
            }
        }
    }
}

private struct SettingsButtonChromeModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        content
            .padding(AccountMetrics.authBlockPadding)
            .background(vocabSkin.palette.pageBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
            )
    }
}

private extension View {
    func appSettingsButtonChrome() -> some View {
        modifier(SettingsButtonChromeModifier())
    }
}
