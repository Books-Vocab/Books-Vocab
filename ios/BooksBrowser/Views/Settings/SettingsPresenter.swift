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
        var sections: [AnyView] = [
            AnyView(SettingsAccountSection(
                state: state.auth,
                manualLoginUserId: manualLoginUserId,
                actions: actions
            ))
        ]

        sections.append(AnyView(SettingsPreferencesSection(
            state: state.preferences,
            actions: actions
        )))

        if let subscription = state.subscription {
            sections.append(AnyView(SettingsSubscriptionSection(
                state: subscription,
                actions: actions
            )))
        }

        if let kg = state.kg {
            sections.append(AnyView(SettingsKGSection(
                state: kg,
                debugLocalServerURL: debugLocalServerURL,
                actions: actions
            )))
        }

        if let optionalIntegration = state.optionalIntegration {
            sections.append(AnyView(optionalIntegrationSection(optionalIntegration)))
        }

        sections.append(AnyView(aboutSection))

        if let danger = state.danger {
            sections.append(AnyView(SettingsDangerSection(
                state: danger,
                actions: actions
            )))
        }

        return sections
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
}

// MARK: - Shared Section Helpers (internal，供各 Section 檔案使用)

struct SettingsSectionHeader: View {
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

struct SettingsSectionFooter: View {
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

typealias SettingsDivider = AppSettingsDivider

struct SettingsRow<Content: View>: View {
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

struct SettingsCardModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        AppSectionCard(padding: 0, style: .settings(vocabSkin)) {
            content
        }
    }
}

extension View {
    func settingsCard() -> some View {
        modifier(SettingsCardModifier())
    }
}

// MARK: - Sheet Views

struct OptionalIntegrationInfoSheetView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: vocabSkin.spacing.sheetSectionSpacing) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.accent)
                        .padding(.bottom, vocabSkin.spacing.inlineGap)

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

                    VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
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
                        .padding(.top, vocabSkin.spacing.actionButtonHorizontalPadding)
                }
                .padding(vocabSkin.spacing.sheetPadding)
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

// MARK: - Preview

private enum SettingsPresenterPreviewData {

    static let noopActions = SettingsPresenterActions(
        dismiss: {},
        loginWithGoogle: {},
        loginWithApple: {},
        logout: {},
        manualLogin: {},
        useProductionBackend: {},
        useLocalBackend: {},
        selectLanguage: { _ in },
        showSubscriptionPaywall: {},
        showOptionalIntegrationInfo: {},
        requestDeleteAccount: {}
    )

    static let loggedOut = SettingsPresenterState(
        auth: .init(
            isLoggedIn: false,
            userInitials: nil,
            avatarURL: nil,
            displayName: "未登入",
            email: nil,
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        ),
        preferences: .init(selectedLanguage: "繁體中文"),
        kg: nil,
        subscription: nil,
        optionalIntegration: nil,
        about: .init(version: "1.0.0 (42)", developerName: "MPSO"),
        danger: nil
    )

    static let subscribedActive = SettingsPresenterState(
        auth: .init(
            isLoggedIn: true,
            userInitials: "CL",
            avatarURL: nil,
            displayName: "Chen Liang",
            email: "chen@example.com",
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        ),
        preferences: .init(selectedLanguage: "繁體中文"),
        kg: .init(
            serverURL: "https://wordnexus.lol",
            isConnected: true,
            connectionPulse: false,
            serverCardCount: 128,
            lastSyncDescription: "3 分鐘前",
            debug: nil
        ),
        subscription: .init(
            planName: "Pro",
            badgeText: "啟用中",
            badgeTone: .success,
            summary: "年度方案，到期日 2027-03-10",
            detail: "感謝支持！所有進階功能已解鎖。",
            sourceLabel: "App Store",
            managementNote: "訂閱狀態由 App Store 管理",
            pricingUnavailableMessage: nil,
            restoreLabel: "恢復購買",
            restoreDescription: "如果您曾購買過訂閱",
            isRestoreAvailable: true,
            ctaTitle: "管理訂閱",
            isRefreshing: false
        ),
        optionalIntegration: .init(isEnabled: true),
        about: .init(version: "1.0.0 (42)", developerName: "MPSO"),
        danger: .init(isDeletingAccount: false)
    )

    static let subscriptionLoading = SettingsPresenterState(
        auth: .init(
            isLoggedIn: true,
            userInitials: "CL",
            avatarURL: nil,
            displayName: "Chen Liang",
            email: "chen@example.com",
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        ),
        preferences: .init(selectedLanguage: "繁體中文"),
        kg: .init(
            serverURL: "https://wordnexus.lol",
            isConnected: false,
            connectionPulse: true,
            serverCardCount: 0,
            lastSyncDescription: nil,
            debug: nil
        ),
        subscription: .init(
            planName: "—",
            badgeText: "載入中",
            badgeTone: .neutral,
            summary: "正在確認訂閱狀態…",
            detail: "請稍候，系統正在與 App Store 通訊。",
            sourceLabel: "確認中",
            managementNote: "正在連線…",
            pricingUnavailableMessage: nil,
            restoreLabel: "恢復購買",
            restoreDescription: "載入中…",
            isRestoreAvailable: false,
            ctaTitle: "重新整理",
            isRefreshing: true
        ),
        optionalIntegration: nil,
        about: .init(version: "1.0.0 (42)", developerName: "MPSO"),
        danger: .init(isDeletingAccount: false)
    )

    static let deletingAccount = SettingsPresenterState(
        auth: .init(
            isLoggedIn: true,
            userInitials: "CL",
            avatarURL: nil,
            displayName: "Chen Liang",
            email: "chen@example.com",
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: nil
        ),
        preferences: .init(selectedLanguage: "繁體中文"),
        kg: .init(
            serverURL: "https://wordnexus.lol",
            isConnected: true,
            connectionPulse: false,
            serverCardCount: 128,
            lastSyncDescription: "剛剛",
            debug: nil
        ),
        subscription: .init(
            planName: "Pro",
            badgeText: "啟用中",
            badgeTone: .success,
            summary: "年度方案",
            detail: "",
            sourceLabel: "App Store",
            managementNote: "訂閱狀態由 App Store 管理",
            pricingUnavailableMessage: nil,
            restoreLabel: "恢復購買",
            restoreDescription: "如果您曾購買過訂閱",
            isRestoreAvailable: true,
            ctaTitle: "管理訂閱",
            isRefreshing: false
        ),
        optionalIntegration: nil,
        about: .init(version: "1.0.0 (42)", developerName: "MPSO"),
        danger: .init(isDeletingAccount: true)
    )
}

#Preview("Settings / Logged Out") {
    AppThemeContainer {
        NavigationStack {
            SettingsPresenter(
                state: SettingsPresenterPreviewData.loggedOut,
                optionalIntegrationApiKey: .constant(""),
                manualLoginUserId: nil,
                debugLocalServerURL: nil,
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}

#Preview("Settings / Subscribed Active") {
    AppThemeContainer {
        NavigationStack {
            SettingsPresenter(
                state: SettingsPresenterPreviewData.subscribedActive,
                optionalIntegrationApiKey: .constant("sk-test-key"),
                manualLoginUserId: nil,
                debugLocalServerURL: nil,
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}

#Preview("Settings / Subscription Loading") {
    AppThemeContainer {
        NavigationStack {
            SettingsPresenter(
                state: SettingsPresenterPreviewData.subscriptionLoading,
                optionalIntegrationApiKey: .constant(""),
                manualLoginUserId: nil,
                debugLocalServerURL: nil,
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}

#Preview("Settings / Deleting Account") {
    AppThemeContainer {
        NavigationStack {
            SettingsPresenter(
                state: SettingsPresenterPreviewData.deletingAccount,
                optionalIntegrationApiKey: .constant(""),
                manualLoginUserId: nil,
                debugLocalServerURL: nil,
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}
