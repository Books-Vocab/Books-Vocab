import SwiftUI

// MARK: - Preview

enum SettingsPresenterPreviewData {

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

        openPrivacyPolicy: {},
        openTermsOfService: {},
        openSupport: {},
        requestAppRating: {},
        resync: {},
        toggleAutoSync: { _ in }
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "跟隨系統", translationSource: "English", translationTarget: "繁體中文", selectedReviewMode: "寬鬆", autoSyncEnabled: false, showAutoSync: false),
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "跟隨系統", translationSource: "English", translationTarget: "繁體中文", selectedReviewMode: "寬鬆", autoSyncEnabled: true, showAutoSync: true),
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
        syncSummary: .init(isConnected: true, isSyncing: false, summaryText: "已連線 · 128 張 · 3 分鐘前"),
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "淺色", translationSource: "English", translationTarget: "繁體中文", selectedReviewMode: "寬鬆", autoSyncEnabled: true, showAutoSync: true),
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
        syncSummary: .init(isConnected: false, isSyncing: false, summaryText: "離線"),
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "深色", translationSource: "English", translationTarget: "繁體中文", selectedReviewMode: "寬鬆", autoSyncEnabled: true, showAutoSync: true),
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
        syncSummary: .init(isConnected: true, isSyncing: false, summaryText: "已連線 · 128 張 · 剛剛"),
        optionalIntegration: nil,
        about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
        danger: .init(isDeletingAccount: true)
    )

    static let pricingUnavailable = SettingsPresenterState(
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
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "跟隨系統", translationSource: "English", translationTarget: "繁體中文", selectedReviewMode: "寬鬆", autoSyncEnabled: true, showAutoSync: true),
        kg: .init(
            serverURL: "https://wordnexus.lol",
            isConnected: true,
            connectionPulse: false,
            serverCardCount: 128,
            lastSyncDescription: "10 分鐘前",
            debug: nil
        ),
        subscription: .init(
            isActive: false,
            planName: "Pro",
            badgeText: "確認中",
            badgeTone: .neutral,
            summary: "免費試用與月費將以 App Store 顯示為準。",
            detail: "目前已取得方案狀態，但價格資訊尚未回來；不影響你稍後進入訂閱頁。",
            sourceLabel: "App Store",
            managementNote: "價格與試用週期會在 App Store 完整顯示。",
            pricingUnavailableMessage: "App Store 價格載入中，稍後會自動更新。",
            restoreLabel: "可恢復購買",
            restoreDescription: "若先前已訂閱但此處顯示未啟用，可在訂閱頁使用恢復購買。",
            isRestoreAvailable: true,
            ctaTitle: "開始免費試用",
            isRefreshing: false
        ),
        syncSummary: .init(isConnected: true, isSyncing: false, summaryText: "已連線 · 128 張 · 10 分鐘前"),
        optionalIntegration: nil,
        about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
        danger: .init(isDeletingAccount: false)
    )

    static let debugBackendLocal = SettingsPresenterState(
        auth: .init(
            isLoggedIn: true,
            userInitials: "CL",
            avatarURL: nil,
            displayName: "Chen Liang",
            email: "chen@example.com",
            authError: nil,
            isAuthenticating: false,
            iconBreathing: false,
            debug: .init(manualLoginHint: "僅供本地測試帳號切換使用".localized)
        ),
        preferences: .init(selectedLanguage: "繁體中文", selectedAppearance: "跟隨系統", translationSource: "English", translationTarget: "繁體中文", selectedReviewMode: "寬鬆", autoSyncEnabled: true, showAutoSync: true),
        kg: .init(
            serverURL: "http://127.0.0.1:8000",
            isConnected: false,
            connectionPulse: true,
            serverCardCount: 12,
            lastSyncDescription: "剛剛",
            debug: .init(
                isUsingLocalServer: true,
                localServerURL: "http://127.0.0.1:8000",
                observation: .init(
                    previewLines: [
                        "12:30:02 [INFO] event=app_session_started",
                        "12:30:05 [INFO] event=background_sync_triggered",
                        "12:30:07 [INFO] event=background_sync_completed duration_ms=1820 success=true"
                    ],
                    totalCount: 24
                )
            )
        ),
        subscription: nil,
        syncSummary: .init(isConnected: false, isSyncing: false, summaryText: "離線"),
        optionalIntegration: .init(isEnabled: true),
        about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
        danger: .init(isDeletingAccount: false)
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

#Preview("Settings / Pricing Unavailable") {
    AppThemeContainer {
        NavigationStack {
            SettingsPresenter(
                state: SettingsPresenterPreviewData.pricingUnavailable,
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

#Preview("Settings / Debug Backend Local") {
    AppThemeContainer {
        NavigationStack {
            SettingsPresenter(
                state: SettingsPresenterPreviewData.debugBackendLocal,
                optionalIntegrationApiKey: .constant(""),
                translationSourceLang: .constant(.en),
                translationTargetLang: .constant(.zhHant),
                onTranslationLanguageChanged: { _, _ in },
                manualLoginUserId: .constant("debug-user-id"),
                debugLocalServerURL: .constant("http://127.0.0.1:8000"),
                actions: SettingsPresenterPreviewData.noopActions
            )
        }
    }
}
