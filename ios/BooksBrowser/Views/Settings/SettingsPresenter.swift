import SwiftUI

struct SettingsPresenter: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin

    let state: SettingsPresenterState
    let optionalIntegrationApiKey: Binding<String>
    let translationSourceLang: Binding<TranslationLanguage>
    let translationTargetLang: Binding<TranslationLanguage>
    let onTranslationLanguageChanged: (TranslationLanguage, TranslationLanguage) -> Void
    let manualLoginUserId: Binding<String>?
    let debugLocalServerURL: Binding<String>?
    let actions: SettingsPresenterActions

    @State private var showAccountDetail = false
    @State private var showSubscriptionDetail = false
    @State private var showTranslationLanguage = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: AppShellMetrics.sectionSpacing) {
                    // Section 1: 帳號
                    accountSection

                    // Section 2: 偏好
                    preferencesSection

                    // Section 3: 其他
                    otherSection

                    // DEBUG 後端切換
                    #if DEBUG
                    if let kg = state.kg, let debugLocalServerURL {
                        debugBackendSection(kg: kg, debugLocalServerURL: debugLocalServerURL)
                    }
                    #endif
                }
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .padding(.top, AppShellMetrics.pageTopPadding)
                .padding(.bottom, AppShellMetrics.pageBottomPadding)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("設定".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized, action: actions.dismiss)
                        .fontWeight(.semibold)
                }
            }
            .navigationDestination(isPresented: $showAccountDetail) {
                SettingsAccountDetailView(
                    authState: state.auth,
                    dangerState: state.danger,
                    actions: actions
                )
            }
            .navigationDestination(isPresented: $showTranslationLanguage) {
                TranslationLanguageSettingsView(
                    sourceLang: translationSourceLang,
                    targetLang: translationTargetLang,
                    onChanged: onTranslationLanguageChanged
                )
            }
            .navigationDestination(isPresented: $showSubscriptionDetail) {
                if let subscription = state.subscription {
                    ScrollView {
                        VStack(spacing: AppShellMetrics.sectionSpacing) {
                            SettingsSubscriptionSection(
                                state: subscription,
                                actions: actions
                            )
                        }
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        .padding(.top, AppShellMetrics.pageTopPadding)
                        .padding(.bottom, AppShellMetrics.pageBottomPadding)
                    }
                    .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
                    .navigationTitle("訂閱".localized)
                    .navigationBarTitleDisplayMode(.inline)
                }
            }
        }
    }

    // MARK: - Section 1: 帳號

    private var accountSection: some View {
        SettingsAccountSection(
            state: state.auth,
            subscription: state.subscription,
            manualLoginUserId: manualLoginUserId,
            actions: actions,
            onShowAccountDetail: { showAccountDetail = true },
            onShowSubscriptionDetail: { showSubscriptionDetail = true }
        )
    }

    // MARK: - Section 2: 偏好

    private var preferencesSection: some View {
        SettingsPreferencesSection(
            state: state.preferences,
            actions: actions
        )
    }

    // MARK: - Section 3: 其他

    private var otherSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "其他".localized, icon: "ellipsis.circle")

            VStack(spacing: 0) {
                // 同步狀態 (only when logged in)
                if let syncSummary = state.syncSummary {
                    syncSummaryRow(syncSummary)
                    SettingsDivider()
                }

                // Mochi 整合 (only when logged in)
                if let optionalIntegration = state.optionalIntegration {
                    mochiRow(optionalIntegration)
                    SettingsDivider()
                }

                // 隱私政策
                Button(action: actions.openPrivacyPolicy) {
                    SettingsRow(icon: "hand.raised", label: "隱私政策".localized) {
                        Image(systemName: "chevron.right")
                            .font(vocabSkin.typography.iconTiny)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                }
                .buttonStyle(.plain)

                SettingsDivider()

                // 支援
                Button(action: actions.openSupport) {
                    SettingsRow(icon: "questionmark.circle", label: "支援".localized) {
                        Image(systemName: "chevron.right")
                            .font(vocabSkin.typography.iconTiny)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                }
                .buttonStyle(.plain)

                SettingsDivider()

                // 為 App 評分
                Button(action: actions.requestAppRating) {
                    SettingsRow(icon: "star", label: "為 App 評分".localized) {
                        Image(systemName: "chevron.right")
                            .font(vocabSkin.typography.iconTiny)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                }
                .buttonStyle(.plain)
            }
            .settingsCard()

            // Version footer
            Text("\("版本".localized) \(state.about.version)")
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .frame(maxWidth: .infinity)
                .padding(.top, vocabSkin.spacing.tinyGap)
        }
    }

    // MARK: - Sync Summary Row

    private func syncSummaryRow(_ summary: SettingsPresenterState.SyncSummaryState) -> some View {
        SettingsRow(icon: "arrow.triangle.2.circlepath", label: "同步狀態".localized) {
            HStack(spacing: 6) {
                Circle()
                    .fill(summary.isConnected ? vocabSkin.palette.success : appTheme.palette.warning)
                    .frame(width: 8, height: 8)
                Text(summary.summaryText)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .lineLimit(1)
            }
        }
    }

    // MARK: - Mochi Row

    private func mochiRow(_ optionalIntegration: SettingsPresenterState.OptionalIntegrationSection) -> some View {
        SettingsRow(icon: "m.square.fill", label: "Mochi API Key") {
            HStack(spacing: 6) {
                SecureField("可選".localized, text: optionalIntegrationApiKey)
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

    // MARK: - DEBUG Backend Section

    #if DEBUG
    private func debugBackendSection(kg: SettingsPresenterState.KGSection, debugLocalServerURL: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "DEBUG 後端".localized, icon: "hammer")

            VStack(spacing: 0) {
                if let debug = kg.debug {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 8) {
                            Button("遠端正式站".localized, action: actions.useProductionBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.quaternaryText : vocabSkin.palette.accent)
                                .accessibilityLabel("切換至遠端正式站".localized)

                            Button("本地開發站".localized, action: actions.useLocalBackend)
                                .buttonStyle(.borderedProminent)
                                .tint(debug.isUsingLocalServer ? vocabSkin.palette.accent : vocabSkin.palette.quaternaryText)
                                .accessibilityLabel("切換至本地開發站".localized)
                        }

                        TextField("本地伺服器 URL".localized, text: debugLocalServerURL)
                            .font(vocabSkin.typography.monoLabel)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)

                        Text(debug.isUsingLocalServer ? "目前使用本地開發站。".localized : "目前使用遠端正式站。".localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                }
            }
            .settingsCard()
        }
    }
    #endif
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

                    Text("關於 Mochi 整合（Legacy）".localized)
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text("如果你仍在使用 Mochi (mochi.cards)，BooksBrowser 可以把你查過並儲存的單字同步過去。這屬於可選的第三方整合，BooksBrowser 本身的雲端同步與複習功能不依賴 Mochi。這個 API Key 會綁定在你的帳號設定，不是伺服器全域設定。".localized)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineSpacing(6)

                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)

                    Text("如何取得 API Key？".localized)
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
                        Label("1. 登入網頁版的 app.mochi.cards".localized, systemImage: "1.circle.fill")
                        Label("2. 點擊右上角設定 (Settings)".localized, systemImage: "2.circle.fill")
                        Label("3. 選擇 API 分頁".localized, systemImage: "3.circle.fill")
                        Label("4. 點擊 Generate API key 並複製貼上到前面設定中".localized, systemImage: "4.circle.fill")
                    }
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.secondaryText)

                    Text("這是保留給既有使用者的可選整合，不填寫 API Key 也不影響 BooksBrowser 的主要功能。".localized)
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
                    Button("完成".localized) { dismiss() }
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
        selectAppearance: { _ in },
        showSubscriptionPaywall: {},
        showOptionalIntegrationInfo: {},
        requestDeleteAccount: {},
        showTranslationLanguageSettings: {},
        openPrivacyPolicy: {},
        openSupport: {},
        requestAppRating: {}
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "跟隨系統", translationSource: "English", translationTarget: "繁體中文"),
        kg: nil,
        subscription: nil,
        syncSummary: nil,
        optionalIntegration: nil,
        about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "跟隨系統", translationSource: "English", translationTarget: "繁體中文"),
        kg: .init(
            serverURL: "https://wordnexus.lol",
            isConnected: true,
            connectionPulse: false,
            serverCardCount: 128,
            lastSyncDescription: "3 分鐘前",
            debug: nil
        ),
        subscription: .init(
            isActive: true,
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
        syncSummary: .init(isConnected: true, summaryText: "已連線 · 128 張 · 3 分鐘前"),
        optionalIntegration: .init(isEnabled: true),
        about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "淺色", translationSource: "English", translationTarget: "繁體中文"),
        kg: .init(
            serverURL: "https://wordnexus.lol",
            isConnected: false,
            connectionPulse: true,
            serverCardCount: 0,
            lastSyncDescription: nil,
            debug: nil
        ),
        subscription: .init(
            isActive: false,
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
        syncSummary: .init(isConnected: false, summaryText: "離線"),
        optionalIntegration: nil,
        about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "深色", translationSource: "English", translationTarget: "繁體中文"),
        kg: .init(
            serverURL: "https://wordnexus.lol",
            isConnected: true,
            connectionPulse: false,
            serverCardCount: 128,
            lastSyncDescription: "剛剛",
            debug: nil
        ),
        subscription: .init(
            isActive: true,
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
        syncSummary: .init(isConnected: true, summaryText: "已連線 · 128 張 · 剛剛"),
        optionalIntegration: nil,
        about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
        danger: .init(isDeletingAccount: true)
    )
}

#Preview("Settings / Logged Out") {
    AppThemeContainer {
        NavigationStack {
            SettingsPresenter(
                state: SettingsPresenterPreviewData.loggedOut,
                optionalIntegrationApiKey: .constant(""),
                translationSourceLang: .constant(.en),
                translationTargetLang: .constant(.zhHant),
                onTranslationLanguageChanged: { _, _ in },
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
                translationSourceLang: .constant(.en),
                translationTargetLang: .constant(.zhHant),
                onTranslationLanguageChanged: { _, _ in },
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
                translationSourceLang: .constant(.en),
                translationTargetLang: .constant(.zhHant),
                onTranslationLanguageChanged: { _, _ in },
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
                translationSourceLang: .constant(.en),
                translationTargetLang: .constant(.zhHant),
                onTranslationLanguageChanged: { _, _ in },
                manualLoginUserId: nil,
                debugLocalServerURL: nil,
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}
