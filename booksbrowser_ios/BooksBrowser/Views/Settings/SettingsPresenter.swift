import SwiftUI

struct SettingsPresenter: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin

    let state: SettingsPresenterState
    let optionalIntegrationApiKey: Binding<String>
    let manualLoginUserId: Binding<String>?
    let debugLocalServerURL: Binding<String>?
    let actions: SettingsPresenterActions

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: AppShellMetrics.sectionSpacing) {
                    ForEach(Array(sectionViews.enumerated()), id: \.offset) { _, section in
                        section
                    }
                }
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .padding(.top, AppShellMetrics.pageTopPadding)
                .padding(.bottom, AppShellMetrics.pageBottomPadding)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成", action: actions.dismiss)
                        .fontWeight(.semibold)
                }
            }
        }
    }

    private var sectionViews: [AnyView] {
        var sections: [AnyView] = [AnyView(authSection)]

        sections.append(AnyView(preferencesSection))

        if let subscription = state.subscription {
            sections.append(AnyView(subscriptionSection(subscription)))
        }

        if let kg = state.kg {
            sections.append(AnyView(kgSection(kg)))
        }

        if let optionalIntegration = state.optionalIntegration {
            sections.append(AnyView(optionalIntegrationSection(optionalIntegration)))
        }

        sections.append(AnyView(aboutSection))

        if let danger = state.danger {
            sections.append(AnyView(dangerSection(danger)))
        }

        return sections
    }

    private var authSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "帳號", icon: "person.crop.circle")

            VStack(spacing: 0) {
                if state.auth.isLoggedIn {
                    loggedInView
                        .transition(.modalSwap)
                } else {
                    loginView
                        .transition(.modalSwap)
                }
            }
            .settingsCard()
            .animation(AppMotion.modalSwapSpring, value: state.auth.isLoggedIn)
        }
    }

    private var preferencesSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "偏好設定", icon: "globe")

            VStack(spacing: 0) {
                SettingsRow(icon: "character.bubble", label: "語言") {
                    Menu {
                        ForEach(AppLanguage.allCases) { language in
                            Button {
                                actions.selectLanguage(language)
                            } label: {
                                if state.preferences.selectedLanguage == L10n.string(language.titleKey) {
                                    Label(L10n.string(language.titleKey), systemImage: "checkmark")
                                } else {
                                    Text(L10n.string(language.titleKey))
                                }
                            }
                        }
                    } label: {
                        HStack(spacing: 6) {
                            Text(state.preferences.selectedLanguage)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                            Image(systemName: "chevron.up.chevron.down")
                                .font(vocabSkin.typography.iconTiny)
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .settingsCard()

            SettingsSectionFooter("切換後會立即套用到 app 介面文字。")
        }
    }

    private var loginView: some View {
        VStack(spacing: 0) {
            VStack(spacing: SettingsMetrics.authHeroSpacing) {
                Image(systemName: "sparkles")
                    .font(vocabSkin.typography.symbolHero)
                    .foregroundStyle(.tertiary)
                    .opacity(state.auth.iconBreathing ? 0.45 : 0.75)
                    .animation(AppMotion.breathing, value: state.auth.iconBreathing)

                VStack(spacing: SettingsMetrics.authCopySpacing) {
                    Text("解鎖完整功能")
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Text("AI 翻譯・知識圖譜・雲端同步")
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }
            }
            .padding(.vertical, SettingsMetrics.authHeroVerticalPadding)
            .frame(maxWidth: .infinity)

            Rectangle()
                .fill(vocabSkin.palette.divider)
                .frame(height: 1)

            VStack(spacing: SettingsMetrics.authActionSpacing) {
                Button(action: actions.loginWithGoogle) {
                    SettingsAuthButton(title: "以 Google 繼續") {
                        SettingsSocialBadge(kind: .google)
                    }
                }
                .buttonStyle(.plain)
                .appSettingsButtonChrome()

                Button(action: actions.loginWithApple) {
                    SettingsAuthButton(title: "以 Apple 繼續") {
                        SettingsSocialBadge(kind: .apple)
                    }
                }
                .buttonStyle(.plain)
                .appSettingsButtonChrome()

#if DEBUG
                if let manualLoginUserId, let debug = state.auth.debug {
                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)
                        .padding(.vertical, 8)

                    HStack(spacing: 8) {
                        TextField("帳號 ID（手動）", text: manualLoginUserId)
                            .font(vocabSkin.typography.monoLabel)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)

                        Button("登入", action: actions.manualLogin)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }

                    if let manualLoginHint = debug.manualLoginHint, !manualLoginHint.isEmpty {
                        Text(manualLoginHint)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
#endif

                if let error = state.auth.authError {
                    Text(error)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.destructive)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 8)
                        .padding(.bottom, 4)
                }
            }
            .padding(.horizontal, SettingsMetrics.authBlockPadding)
            .padding(.vertical, SettingsMetrics.authBlockPadding)
        }
    }

    private var loggedInView: some View {
        VStack(spacing: 0) {
            SettingsAuthSummary(state: state.auth)
            .padding(vocabSkin.spacing.cardPadding)

            Rectangle()
                .fill(vocabSkin.palette.divider)
                .frame(height: 1)

            Button(role: .destructive, action: actions.logout) {
                Text("登出帳號")
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.destructive)
            }
            .buttonStyle(.appAction(.destructive))
            .padding(vocabSkin.spacing.cardPadding)
        }
    }

    private func kgSection(_ kg: SettingsPresenterState.KGSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "Knowledge Graph", icon: "brain.head.profile")

            VStack(spacing: 0) {
                SettingsRow(icon: "server.rack", label: "伺服器") {
                    Text(kg.serverURL)
                        .font(vocabSkin.typography.monoLabel)
                        .multilineTextAlignment(.trailing)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                SettingsDivider()

                SettingsRow(icon: "antenna.radiowaves.left.and.right", label: "連線狀態") {
                    HStack(spacing: 8) {
                        let statusTone = kg.isConnected ? vocabSkin.palette.success : appTheme.palette.warning
                        Circle()
                            .fill(statusTone)
                            .frame(width: 8, height: 8)
                            .shadow(
                                color: statusTone.opacity(0.6),
                                radius: kg.connectionPulse ? 5 : 2
                            )
                        Text((kg.isConnected ? "已連線" : "離線").localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                }

                if kg.isConnected {
                    SettingsDivider()

                    SettingsRow(icon: "text.book.closed", label: "字庫卡片") {
                        Text(L10n.format("%@ 張", "\(kg.serverCardCount)"))
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                    .transition(.statusRowReveal)

                    if let lastSyncDescription = kg.lastSyncDescription {
                        SettingsDivider()

                        SettingsRow(icon: "arrow.clockwise", label: "最後同步") {
                            Text(lastSyncDescription)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                        .transition(.statusRowReveal)
                    }
                }

#if DEBUG
                if let debug = kg.debug, let debugLocalServerURL {
                    SettingsDivider()

                    VStack(alignment: .leading, spacing: 12) {
                        Text("DEBUG 後端")
                            .font(vocabSkin.typography.captionStrong)
                            .foregroundStyle(vocabSkin.palette.secondaryText)

                        HStack(spacing: 8) {
                            Button("遠端正式站", action: actions.useProductionBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.quaternaryText : vocabSkin.palette.accent)

                            Button("本地開發站", action: actions.useLocalBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.accent : vocabSkin.palette.quaternaryText)
                        }

                        TextField("本地伺服器 URL", text: debugLocalServerURL)
                            .font(vocabSkin.typography.monoLabel)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)

                        Text(debug.isUsingLocalServer ? "目前使用本地開發站。" : "目前使用遠端正式站。")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                }
#endif
            }
            .settingsCard()
            .animation(AppMotion.emphasizedSpring, value: kg.isConnected)
            .animation(AppMotion.emphasizedSpring, value: kg.serverCardCount)

            SettingsSectionFooter("KG 伺服器負責生詞 AI 增強、知識連結與可選的第三方整合。")
        }
    }

    private func subscriptionSection(_ subscription: SettingsPresenterState.SubscriptionSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "訂閱", icon: "sparkles.rectangle.stack")

            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(subscription.planName)
                                .font(vocabSkin.typography.sectionTitle)
                                .foregroundStyle(vocabSkin.palette.primaryText)

                            Text(subscription.summary)
                                .font(vocabSkin.typography.body)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .lineSpacing(4)
                        }

                        Spacer()

                        subscriptionBadge(subscription)
                    }

                    Text(subscription.detail)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)

                    if let pricingUnavailableMessage = subscription.pricingUnavailableMessage {
                        VocabStateMessageCard(
                            title: "App Store 價格暫時不可用",
                            systemImage: "exclamationmark.triangle.fill",
                            description: pricingUnavailableMessage
                        )
                        .transition(.statusRowReveal)
                    }

                    subscriptionMetaRow(
                        title: "權限來源",
                        value: subscription.sourceLabel
                    )
                    .transition(.statusRowReveal)

                    subscriptionMetaRow(
                        title: subscription.restoreLabel,
                        value: subscription.restoreDescription,
                        emphasized: subscription.isRestoreAvailable
                    )
                    .transition(.statusRowReveal)

                    subscriptionMetaRow(
                        title: "管理方式",
                        value: subscription.managementNote
                    )
                    .transition(.statusRowReveal)

                    Button(action: actions.showSubscriptionPaywall) {
                        HStack(spacing: 10) {
                            if subscription.isRefreshing {
                                ProgressView()
                                    .controlSize(.small)
                            } else {
                                Image(systemName: "arrow.right.circle.fill")
                                    .font(vocabSkin.typography.iconMedium)
                            }

                            Text(subscription.ctaTitle)
                                .font(vocabSkin.typography.body.weight(.medium))

                            Spacer()
                        }
                        .foregroundStyle(vocabSkin.palette.primaryText)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 12)
                        .background(vocabSkin.palette.pageBackground)
                        .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(subscription.isRefreshing)
                }
                .padding(vocabSkin.spacing.cardPadding)
            }
            .settingsCard()
            .animation(AppMotion.phaseChange, value: subscription.badgeText)
            .animation(AppMotion.phaseChange, value: subscription.pricingUnavailableMessage)

            SettingsSectionFooter("Pro 權限由後端統一管理；來源可能是 App Store 訂閱或管理員手動授權。")
        }
    }

    private func subscriptionMetaRow(
        title: String,
        value: String,
        emphasized: Bool = false
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(emphasized ? vocabSkin.palette.accent : vocabSkin.palette.tertiaryText)

            Text(value)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func optionalIntegrationSection(_ optionalIntegration: SettingsPresenterState.OptionalIntegrationSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "可選整合", icon: "puzzlepiece.extension")

            VStack(spacing: 0) {
                SettingsRow(icon: "m.square.fill", label: "Mochi API Key (Legacy)") {
                    HStack(spacing: 6) {
                        SecureField("可選", text: optionalIntegrationApiKey)
                            .font(vocabSkin.typography.monoLabel)
                            .multilineTextAlignment(.trailing)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .disabled(!optionalIntegration.isEnabled)

                        Button(action: actions.showOptionalIntegrationInfo) {
                            Image(systemName: "info.circle")
                                .font(vocabSkin.typography.iconMedium)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .settingsCard()

            SettingsSectionFooter("Legacy optional。只有在你仍使用 Mochi 時才需要填寫；BooksBrowser 的雲端同步與複習不依賴它。")
        }
    }

    private var aboutSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "關於", icon: "info.circle")

            VStack(spacing: 0) {
                SettingsRow(icon: "tag", label: "版本") {
                    Text(state.about.version)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                SettingsDivider()

                SettingsRow(icon: "person.circle", label: "開發者") {
                    Text(state.about.developerName)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

            }
            .settingsCard()
        }
    }

    private func dangerSection(_ danger: SettingsPresenterState.DangerSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "危險操作", icon: "exclamationmark.triangle")

            VStack(spacing: 0) {
                Button(role: .destructive, action: actions.requestDeleteAccount) {
                    HStack {
                        Text((danger.isDeletingAccount ? "刪除中..." : "刪除帳號與雲端資料").localized)
                            .font(vocabSkin.typography.body)
                            .foregroundStyle(vocabSkin.palette.destructive)
                        Spacer()
                        Image(systemName: "trash")
                            .font(vocabSkin.typography.iconTiny)
                            .foregroundStyle(vocabSkin.palette.destructive)
                    }
                }
                .buttonStyle(.appAction(.destructive))
                .disabled(danger.isDeletingAccount)
            }
            .settingsCard()

            SettingsSectionFooter("此操作不可逆，會刪除帳號與所有雲端資料。")
        }
    }
}

private extension SettingsPresenter {
    func subscriptionBadge(_ subscription: SettingsPresenterState.SubscriptionSection) -> some View {
        let tone: Color
        switch subscription.badgeTone {
        case .neutral:
            tone = vocabSkin.palette.secondaryText
        case .accent:
            tone = vocabSkin.palette.accent
        case .success:
            tone = vocabSkin.palette.success
        }

        return Text(subscription.badgeText)
            .font(vocabSkin.typography.monoLabel)
            .foregroundStyle(tone)
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(tone.opacity(0.12))
            .clipShape(Capsule())
    }
}

private struct SettingsSectionHeader: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let icon: String

    var body: some View {
        AppSectionHeader(
            title: title,
            systemImage: icon,
            style: .init(
                font: vocabSkin.typography.captionStrong,
                color: vocabSkin.palette.secondaryText
            )
        )
    }
}

private struct SettingsSectionFooter: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        AppSectionFooter(
            text: text,
            style: .init(
                font: vocabSkin.typography.caption,
                color: vocabSkin.palette.tertiaryText
            )
        )
    }
}

private struct SettingsDivider: View {
    @Environment(\.vocabSkin) private var vocabSkin

    var body: some View {
        Rectangle()
            .fill(vocabSkin.palette.divider)
            .frame(height: 1)
            .padding(.leading, 50)
    }
}

private enum SettingsSocialKind {
    case google
    case apple
}

private enum SettingsMetrics {
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
    static let authSocialShadowRadius: CGFloat = 2
    static let authSocialShadowY: CGFloat = 1
}

private struct SettingsSocialBadge: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let kind: SettingsSocialKind

    var body: some View {
        ZStack {
            Circle()
                .fill(backgroundColor)
                .frame(
                    width: SettingsMetrics.authSocialBadgeSize,
                    height: SettingsMetrics.authSocialBadgeSize
                )
                .shadow(
                    color: shadowColor,
                    radius: SettingsMetrics.authSocialShadowRadius,
                    y: SettingsMetrics.authSocialShadowY
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
                        .foregroundStyle(.white)
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
        HStack(spacing: SettingsMetrics.authButtonSpacing) {
            leading

            Text(title.localized)
                .font(vocabSkin.typography.body.weight(.medium))

            Spacer()

            Image(systemName: "chevron.right")
                .font(vocabSkin.typography.iconTiny)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
        }
    }
}

private struct SettingsAuthSummary: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let state: SettingsPresenterState.AuthSection

    var body: some View {
        HStack(spacing: SettingsMetrics.authRowSpacing) {
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

            VStack(alignment: .trailing, spacing: SettingsMetrics.authStatusSpacing) {
                Image(systemName: "checkmark.circle.fill")
                    .font(vocabSkin.typography.symbolLarge)
                    .foregroundStyle(vocabSkin.palette.success)
                    .symbolEffect(.bounce, value: state.isLoggedIn)
            }
        }
    }

    @ViewBuilder
    private var avatar: some View {
        ZStack {
            Circle()
                .fill(vocabSkin.palette.mutedFill)
                .frame(
                    width: SettingsMetrics.authAvatarSize,
                    height: SettingsMetrics.authAvatarSize
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
                    width: SettingsMetrics.authAvatarSize,
                    height: SettingsMetrics.authAvatarSize
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

private struct SettingsRow<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let icon: String
    let label: String
    let content: Content

    init(icon: String, label: String, @ViewBuilder content: () -> Content) {
        self.icon = icon
        self.label = label
        self.content = content()
    }

    var body: some View {
        AppKeyValueRow(
            icon: icon,
            label: label,
            style: .settings(vocabSkin)
        ) {
            content
        }
    }
}

private extension View {
    func settingsCard() -> some View {
        modifier(SettingsCardModifier())
    }
}

private struct SettingsCardModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        AppSectionCard(padding: 0, style: .settings(vocabSkin)) {
            content
        }
    }
}

private struct SettingsButtonChromeModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        content
            .padding(SettingsMetrics.authBlockPadding)
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

struct OptionalIntegrationInfoSheetView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.accent)
                        .padding(.bottom, 8)

                    Text("關於 Mochi 整合（Legacy）")
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text("如果你仍在使用 Mochi (mochi.cards)，BooksBrowser 可以把你查過並儲存的單字同步過去。這屬於可選的第三方整合，BooksBrowser 本身的雲端同步與複習功能不依賴 Mochi。這個 API Key 會綁定在你的帳號設定，不是伺服器全域設定。")
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineSpacing(6)

                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)

                    Text("如何取得 API Key？")
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    VStack(alignment: .leading, spacing: 12) {
                        Label("1. 登入網頁版的 app.mochi.cards", systemImage: "1.circle.fill")
                        Label("2. 點擊右上角設定 (Settings)", systemImage: "2.circle.fill")
                        Label("3. 選擇 API 分頁", systemImage: "3.circle.fill")
                        Label("4. 點擊 Generate API key 並複製貼上到前面設定中", systemImage: "4.circle.fill")
                    }
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.secondaryText)

                    Text("這是保留給既有使用者的可選整合，不填寫 API Key 也不影響 BooksBrowser 的主要功能。")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                        .padding(.top, 16)
                }
                .padding(24)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

struct SubscriptionPaywallSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Image(systemName: "sparkles.rectangle.stack.fill")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.accent)

                    Text("BooksBrowser Pro")
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text(paywallSummaryText)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineSpacing(6)

                    VStack(alignment: .leading, spacing: 6) {
                        Text(priceLine)
                            .font(vocabSkin.typography.sectionTitle)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                        Text(L10n.format("權限來源：%@", entitlementSourceLine))
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                        Text(L10n.format("打開位置：%@", sourceLine))
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }

                    accessStateCard

                    VStack(alignment: .leading, spacing: 12) {
                        paywallFeatureRow("AI 翻譯與語境解釋")
                        paywallFeatureRow("知識庫同步與跨裝置狀態")
                        paywallFeatureRow("關聯圖與內建複習")
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                    .background(vocabSkin.palette.cardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                            .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                    )

                    VStack(spacing: 10) {
                        Button {
                            Task {
                                if isAdminGranted {
                                    await subscriptionManager.refresh(using: kgService, authManager: authManager)
                                } else if subscriptionManager.hasProAccess {
                                    await subscriptionManager.refresh(using: kgService, authManager: authManager)
                                } else {
                                    await subscriptionManager.purchasePro(using: kgService, authManager: authManager)
                                }
                            }
                        } label: {
                            HStack {
                                if subscriptionManager.isLoading {
                                    ProgressView()
                                        .controlSize(.small)
                                }
                                Text(primaryActionTitle)
                                Spacer()
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.vocabAction(.primary))
                        .disabled(subscriptionManager.isLoading)

                        if !isAdminGranted {
                            Button {
                                Task {
                                    await subscriptionManager.restorePurchases(using: kgService, authManager: authManager)
                                }
                            } label: {
                                Text("恢復購買")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.vocabAction(.neutral))
                            .disabled(subscriptionManager.isLoading)
                        } else {
                            VocabStateMessageCard(
                                title: "恢復購買不適用",
                                systemImage: "person.badge.key",
                                description: "目前權限來自管理員授權；若需調整，請由管理員或後端 /admin 處理。"
                            )
                        }
                    }

                    if let purchaseStatusMessage = subscriptionManager.purchaseStatusMessage {
                        VocabStateMessageCard(
                            title: purchaseStatusMessage,
                            systemImage: "checkmark.circle"
                        )
                    }

                    if let lastError = subscriptionManager.lastError, !lastError.isEmpty {
                        VocabStateMessageCard(
                            title: "App Store 載入失敗",
                            systemImage: "exclamationmark.triangle.fill",
                            description: lastError
                        ) {
                            Text(L10n.format("目前商品 ID：%@", subscriptionManager.proProductIdentifier))
                                .font(vocabSkin.typography.monoLabel)
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                                .textSelection(.enabled)
                        }
                    }

                    Text(footerNote)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                .padding(20)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("訂閱")
            .navigationBarTitleDisplayMode(.inline)
            .task {
                await subscriptionManager.loadProducts()
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }

    private var paywallSummaryText: String {
        if isAdminGranted {
            return L10n.string("目前帳號已由管理員授權為 Pro。功能已啟用，但這個權限不經由 App Store 管理。")
        }
        if subscriptionManager.hasProAccess {
            return L10n.string("目前帳號已具備 Pro 權限。若狀態顯示不一致，可重新同步或恢復購買。")
        }
        return L10n.string("解鎖閱讀器 AI、知識庫同步、關聯圖與內建複習。免費試用與價格會直接來自 App Store。")
    }

    private var priceLine: String {
        if isAdminGranted {
            if let expiresAt = subscriptionManager.entitlements.pro.expires_at, !expiresAt.isEmpty {
                return L10n.format("管理員授權 · 有效至 %@", expiresAt)
            }
            return L10n.string("管理員授權")
        }
        if let product = subscriptionManager.proProduct {
            let days = subscriptionManager.entitlements.pro.trial_days ?? 7
            return L10n.format("%@ / month · %@ 天免費試用", product.displayPrice, "\(days)")
        }
        if let remotePrice = subscriptionManager.entitlements.pro.price_display, !remotePrice.isEmpty {
            return remotePrice
        }
        if let lastError = subscriptionManager.lastError, !lastError.isEmpty {
            return L10n.string("無法載入 App Store 價格")
        }
        return L10n.string("載入 App Store 價格中…")
    }

    private var entitlementSourceLine: String {
        switch subscriptionManager.entitlements.pro.source {
        case "admin":
            return L10n.string("管理員授權")
        default:
            return L10n.string("App Store 訂閱")
        }
    }

    private var sourceLine: String {
        switch subscriptionManager.activePaywallSource {
        case .settings:
            return "設定"
        case .sync:
            return "同步"
        case .graph:
            return "關聯圖"
        case .reader:
            return "閱讀器 AI"
        case .knowledge:
            return "知識庫"
        case nil:
            return "訂閱"
        }
    }

    private var isAdminGranted: Bool {
        subscriptionManager.entitlements.pro.is_active && subscriptionManager.entitlements.pro.source == "admin"
    }

    private var primaryActionTitle: String {
        if isAdminGranted {
            return L10n.string("重新整理權限狀態")
        }
        if subscriptionManager.hasProAccess {
            return L10n.string("重新同步訂閱狀態")
        }
        return L10n.string("開始免費試用")
    }

    private var footerNote: String {
        if isAdminGranted {
            return L10n.string("此帳號目前由管理員授權為 Pro；若需延長、撤銷或調整權限，請在後端 /admin 處理。")
        }
        return L10n.string("價格與免費試用長度會以 App Store 與你的地區顯示為準。")
    }

    private var accessStateCard: some View {
        Group {
            if isAdminGranted {
                VocabStateMessageCard(
                    title: "管理員授權中",
                    systemImage: "person.badge.key.fill",
                    description: "此 Pro 狀態不走 App Store 續訂流程，這裡主要提供狀態查看與重新整理。"
                )
            } else if subscriptionManager.entitlements.pro.is_trial {
                VocabStateMessageCard(
                    title: "免費試用中",
                    systemImage: "timer",
                    description: "試用到期前可完整使用 Reader AI、同步、關聯圖與複習功能。"
                )
            } else if subscriptionManager.hasProAccess {
                VocabStateMessageCard(
                    title: "App Store 訂閱已啟用",
                    systemImage: "checkmark.circle.fill",
                    description: "若不同裝置顯示不一致，可重新同步訂閱狀態或恢復購買。"
                )
            } else {
                VocabStateMessageCard(
                    title: "尚未啟用 Pro",
                    systemImage: "sparkles.rectangle.stack",
                    description: "價格、免費試用與續訂規則都會以 App Store 實際顯示為準。"
                )
            }
        }
    }

    private func paywallFeatureRow(_ text: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "checkmark.circle.fill")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.success)
            Text(text)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.primaryText)
            Spacer()
        }
    }
}
