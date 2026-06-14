import Foundation

enum SettingsFixtureID: String, CaseIterable {
    case loggedOut = "logged_out"
    case accountLoggedOutError = "account_logged_out_error"
    case preferencesAutoSyncOff = "preferences_auto_sync_off"
    case preferencesLoggedOutNoSync = "preferences_logged_out_no_sync"
    case subscribedActive = "subscribed_active"
    case accountLongIdentity = "account_long_identity"
    case subscriptionFree = "subscription_free"
    case subscriptionLoading = "subscription_loading"
    case deletingAccount = "deleting_account"
    case pricingUnavailable = "pricing_unavailable"
    case debugBackendLocal = "debug_backend_local"

    var key: FixtureKey {
        FixtureKey("settings.\(rawValue)")
    }
}

struct SettingsFixtureSeed: Codable {
    struct Auth: Codable {
        let isLoggedIn: Bool
        let userInitials: String?
        let avatarURL: URL?
        let displayName: String
        let email: String?
        let authError: String?
        let isAuthenticating: Bool
        let iconBreathing: Bool
        let manualLoginHint: String?
    }

    struct KG: Codable {
        struct Observation: Codable {
            let previewLines: [String]
            let totalCount: Int
        }

        let serverURL: String
        let isConnected: Bool
        let connectionPulse: Bool
        let serverCardCount: Int
        let lastSyncDescription: String?
        let isUsingLocalServer: Bool
        let localServerURL: String?
        let observation: Observation?
    }

    struct Subscription: Codable {
        let isActive: Bool
        let planName: String
        let badgeText: String
        let badgeTone: SubscriptionBadgeTone
        let summary: String
        let detail: String
        let sourceLabel: String
        let managementNote: String
        let pricingUnavailableMessage: String?
        let restoreLabel: String
        let restoreDescription: String
        let isRestoreAvailable: Bool
        let ctaTitle: String
        let isRefreshing: Bool
    }

    struct Preferences: Codable {
        let selectedLanguage: String
        let selectedAppearance: String
        let translationSource: String
        let translationTarget: String
        let selectedReviewMode: String
        let autoSyncEnabled: Bool
        let showAutoSync: Bool
    }

    struct SyncSummary: Codable {
        let isConnected: Bool
        let isSyncing: Bool
        let summaryText: String
    }

    struct About: Codable {
        let version: String
        let developerName: String
    }

    struct Danger: Codable {
        let isDeletingAccount: Bool
    }

    struct BookSync: Codable {
        enum Tone: String, Codable {
            case progress
            case success
            case warning
        }

        let text: String
        let detail: String?
        let tone: Tone
    }

    let auth: Auth
    let preferences: Preferences
    let kg: KG?
    let subscription: Subscription?
    let syncSummary: SyncSummary?
    // var + default：讓既有 seed 建構處免改（同 SettingsPresenterState.bookSync）。
    var bookSync: BookSync? = nil
    let about: About
    let danger: Danger?
    let manualLoginUserId: String?
    let debugLocalServerURL: String?
}

struct SettingsFixtureRenderModel {
    let state: SettingsPresenterState
    let manualLoginUserId: String?
    let debugLocalServerURL: String?
}

enum SettingsFixtures {
    private static let sharedSurfaces: Set<FixtureSurface> = [.preview, .catalog, .snapshot]

    private static let registry = FixtureRegistry<SettingsFixtureSeed>([
        FixtureRecipe(key: SettingsFixtureID.loggedOut.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
                auth: .init(
                    isLoggedIn: false,
                    userInitials: nil,
                    avatarURL: nil,
                    displayName: "未登入",
                    email: nil,
                    authError: nil,
                    isAuthenticating: false,
                    iconBreathing: false,
                    manualLoginHint: nil
                ),
                preferences: .init(
                    selectedLanguage: "繁體中文",
                    selectedAppearance: "跟隨系統",
                    translationSource: "English",
                    translationTarget: "繁體中文",
                    selectedReviewMode: "寬鬆",
                    autoSyncEnabled: false,
                    showAutoSync: false
                ),
                kg: nil,
                subscription: nil,
                syncSummary: nil,
                about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
                danger: nil,
                manualLoginUserId: nil,
                debugLocalServerURL: nil
            )
        },
        FixtureRecipe(key: SettingsFixtureID.accountLoggedOutError.key, surfaces: sharedSurfaces, tags: ["edge"]) {
            FixtureDatasetStore.requireSettingsSeed(for: .accountLoggedOutError)
        },
        FixtureRecipe(key: SettingsFixtureID.preferencesAutoSyncOff.key, surfaces: sharedSurfaces, tags: ["preferences"]) {
            FixtureDatasetStore.requireSettingsSeed(for: .preferencesAutoSyncOff)
        },
        FixtureRecipe(key: SettingsFixtureID.preferencesLoggedOutNoSync.key, surfaces: sharedSurfaces, tags: ["preferences"]) {
            FixtureDatasetStore.requireSettingsSeed(for: .preferencesLoggedOutNoSync)
        },
        FixtureRecipe(key: SettingsFixtureID.subscribedActive.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
                auth: .init(
                    isLoggedIn: true,
                    userInitials: "CL",
                    avatarURL: nil,
                    displayName: "Chen Liang",
                    email: "chen@example.com",
                    authError: nil,
                    isAuthenticating: false,
                    iconBreathing: false,
                    manualLoginHint: nil
                ),
                preferences: .init(
                    selectedLanguage: "繁體中文",
                    selectedAppearance: "跟隨系統",
                    translationSource: "English",
                    translationTarget: "繁體中文",
                    selectedReviewMode: "寬鬆",
                    autoSyncEnabled: true,
                    showAutoSync: true
                ),
                kg: .init(
                    serverURL: BrandIdentity.publicBaseURL,
                    isConnected: true,
                    connectionPulse: false,
                    serverCardCount: 128,
                    lastSyncDescription: "3 分鐘前",
                    isUsingLocalServer: false,
                    localServerURL: nil,
                    observation: nil
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
                bookSync: .init(text: "已同步", detail: nil, tone: .success),
                about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
                danger: .init(isDeletingAccount: false),
                manualLoginUserId: nil,
                debugLocalServerURL: nil
            )
        },
        FixtureRecipe(key: SettingsFixtureID.accountLongIdentity.key, surfaces: sharedSurfaces, tags: ["edge"]) {
            FixtureDatasetStore.requireSettingsSeed(for: .accountLongIdentity)
        },
        FixtureRecipe(key: SettingsFixtureID.subscriptionFree.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            FixtureDatasetStore.requireSettingsSeed(for: .subscriptionFree)
        },
        FixtureRecipe(key: SettingsFixtureID.subscriptionLoading.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
                auth: .init(
                    isLoggedIn: true,
                    userInitials: "CL",
                    avatarURL: nil,
                    displayName: "Chen Liang",
                    email: "chen@example.com",
                    authError: nil,
                    isAuthenticating: false,
                    iconBreathing: false,
                    manualLoginHint: nil
                ),
                preferences: .init(
                    selectedLanguage: "繁體中文",
                    selectedAppearance: "淺色",
                    translationSource: "English",
                    translationTarget: "繁體中文",
                    selectedReviewMode: "寬鬆",
                    autoSyncEnabled: true,
                    showAutoSync: true
                ),
                kg: .init(
                    serverURL: BrandIdentity.publicBaseURL,
                    isConnected: false,
                    connectionPulse: true,
                    serverCardCount: 0,
                    lastSyncDescription: nil,
                    isUsingLocalServer: false,
                    localServerURL: nil,
                    observation: nil
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
                about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
                danger: .init(isDeletingAccount: false),
                manualLoginUserId: nil,
                debugLocalServerURL: nil
            )
        },
        FixtureRecipe(key: SettingsFixtureID.deletingAccount.key, surfaces: sharedSurfaces, tags: ["edge"]) {
            .init(
                auth: .init(
                    isLoggedIn: true,
                    userInitials: "CL",
                    avatarURL: nil,
                    displayName: "Chen Liang",
                    email: "chen@example.com",
                    authError: nil,
                    isAuthenticating: false,
                    iconBreathing: false,
                    manualLoginHint: nil
                ),
                preferences: .init(
                    selectedLanguage: "繁體中文",
                    selectedAppearance: "深色",
                    translationSource: "English",
                    translationTarget: "繁體中文",
                    selectedReviewMode: "寬鬆",
                    autoSyncEnabled: true,
                    showAutoSync: true
                ),
                kg: .init(
                    serverURL: BrandIdentity.publicBaseURL,
                    isConnected: true,
                    connectionPulse: false,
                    serverCardCount: 128,
                    lastSyncDescription: "剛剛",
                    isUsingLocalServer: false,
                    localServerURL: nil,
                    observation: nil
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
                about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
                danger: .init(isDeletingAccount: true),
                manualLoginUserId: nil,
                debugLocalServerURL: nil
            )
        },
        FixtureRecipe(key: SettingsFixtureID.pricingUnavailable.key, surfaces: sharedSurfaces, tags: ["edge"]) {
            .init(
                auth: .init(
                    isLoggedIn: true,
                    userInitials: "CL",
                    avatarURL: nil,
                    displayName: "Chen Liang",
                    email: "chen@example.com",
                    authError: nil,
                    isAuthenticating: false,
                    iconBreathing: false,
                    manualLoginHint: nil
                ),
                preferences: .init(
                    selectedLanguage: "繁體中文",
                    selectedAppearance: "跟隨系統",
                    translationSource: "English",
                    translationTarget: "繁體中文",
                    selectedReviewMode: "寬鬆",
                    autoSyncEnabled: true,
                    showAutoSync: true
                ),
                kg: .init(
                    serverURL: BrandIdentity.publicBaseURL,
                    isConnected: true,
                    connectionPulse: false,
                    serverCardCount: 128,
                    lastSyncDescription: "10 分鐘前",
                    isUsingLocalServer: false,
                    localServerURL: nil,
                    observation: nil
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
                bookSync: .init(text: "同步異常", detail: "iCloud 帳號暫時無法使用（CKError.notAuthenticated）", tone: .warning),
                about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
                danger: .init(isDeletingAccount: false),
                manualLoginUserId: nil,
                debugLocalServerURL: nil
            )
        },
        FixtureRecipe(key: SettingsFixtureID.debugBackendLocal.key, surfaces: sharedSurfaces, tags: ["debug"]) {
            .init(
                auth: .init(
                    isLoggedIn: true,
                    userInitials: "CL",
                    avatarURL: nil,
                    displayName: "Chen Liang",
                    email: "chen@example.com",
                    authError: nil,
                    isAuthenticating: false,
                    iconBreathing: false,
                    manualLoginHint: "僅供本地測試帳號切換使用"
                ),
                preferences: .init(
                    selectedLanguage: "繁體中文",
                    selectedAppearance: "跟隨系統",
                    translationSource: "English",
                    translationTarget: "繁體中文",
                    selectedReviewMode: "寬鬆",
                    autoSyncEnabled: true,
                    showAutoSync: true
                ),
                kg: .init(
                    serverURL: "http://127.0.0.1:8000",
                    isConnected: false,
                    connectionPulse: true,
                    serverCardCount: 12,
                    lastSyncDescription: "剛剛",
                    isUsingLocalServer: true,
                    localServerURL: "http://127.0.0.1:8000",
                    observation: .init(
                        previewLines: [
                            "12:30:02 [INFO] event=app_session_started",
                            "12:30:05 [INFO] event=background_sync_triggered",
                            "12:30:07 [INFO] event=background_sync_completed duration_ms=1820 success=true",
                        ],
                        totalCount: 24
                    )
                ),
                subscription: nil,
                syncSummary: .init(isConnected: false, isSyncing: false, summaryText: "離線"),
                about: .init(version: "1.1.0 (42)", developerName: "MPSO"),
                danger: .init(isDeletingAccount: false),
                manualLoginUserId: "debug-user-id",
                debugLocalServerURL: "http://127.0.0.1:8000"
            )
        },
    ])

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<SettingsFixtureSeed>] {
        registry.recipes(for: surface)
    }

    static func state(for fixtureID: SettingsFixtureID) -> SettingsPresenterState {
        renderModel(for: fixtureID).state
    }

    static func renderModel(for fixtureID: SettingsFixtureID) -> SettingsFixtureRenderModel {
        let seed = FixtureDatasetStore.requireSettingsSeed(for: fixtureID)
        return .init(
            state: SettingsFixtureAdapter.makeState(from: seed),
            manualLoginUserId: seed.manualLoginUserId,
            debugLocalServerURL: seed.debugLocalServerURL
        )
    }
}

private enum SettingsFixtureAdapter {
    static func makeState(from seed: SettingsFixtureSeed) -> SettingsPresenterState {
        SettingsPresenterState(
            auth: .init(
                isLoggedIn: seed.auth.isLoggedIn,
                userInitials: seed.auth.userInitials,
                avatarURL: seed.auth.avatarURL,
                displayName: seed.auth.displayName,
                email: seed.auth.email,
                authError: seed.auth.authError,
                isAuthenticating: seed.auth.isAuthenticating,
                iconBreathing: seed.auth.iconBreathing,
                debug: seed.auth.manualLoginHint.map { .init(manualLoginHint: $0.localized) }
            ),
            preferences: .init(
                selectedLanguage: seed.preferences.selectedLanguage,
                selectedAppearance: seed.preferences.selectedAppearance,
                translationSource: seed.preferences.translationSource,
                translationTarget: seed.preferences.translationTarget,
                selectedReviewMode: seed.preferences.selectedReviewMode,
                autoSyncEnabled: seed.preferences.autoSyncEnabled,
                showAutoSync: seed.preferences.showAutoSync
            ),
            kg: seed.kg.map { kg in
                .init(
                    serverURL: kg.serverURL,
                    isConnected: kg.isConnected,
                    connectionPulse: kg.connectionPulse,
                    serverCardCount: kg.serverCardCount,
                    lastSyncDescription: kg.lastSyncDescription,
                    debug: makeDebugSection(from: kg)
                )
            },
            subscription: seed.subscription.map { subscription in
                .init(
                    isActive: subscription.isActive,
                    planName: subscription.planName,
                    badgeText: subscription.badgeText,
                    badgeTone: subscription.badgeTone,
                    summary: subscription.summary,
                    detail: subscription.detail,
                    sourceLabel: subscription.sourceLabel,
                    managementNote: subscription.managementNote,
                    pricingUnavailableMessage: subscription.pricingUnavailableMessage,
                    restoreLabel: subscription.restoreLabel,
                    restoreDescription: subscription.restoreDescription,
                    isRestoreAvailable: subscription.isRestoreAvailable,
                    ctaTitle: subscription.ctaTitle,
                    isRefreshing: subscription.isRefreshing
                )
            },
            syncSummary: seed.syncSummary.map {
                .init(isConnected: $0.isConnected, isSyncing: $0.isSyncing, summaryText: $0.summaryText)
            },
            bookSync: seed.bookSync.map {
                .init(text: $0.text, detail: $0.detail, tone: makeBookSyncTone($0.tone))
            },
            about: .init(version: seed.about.version, developerName: seed.about.developerName),
            danger: seed.danger.map { .init(isDeletingAccount: $0.isDeletingAccount) }
        )
    }

    private static func makeBookSyncTone(_ tone: SettingsFixtureSeed.BookSync.Tone) -> SettingsPresenterState.BookSyncState.Tone {
        switch tone {
        case .progress: return .progress
        case .success:  return .success
        case .warning:  return .warning
        }
    }

    private static func makeDebugSection(from kg: SettingsFixtureSeed.KG) -> SettingsPresenterState.KGSection.DebugSection? {
        guard kg.isUsingLocalServer, let localServerURL = kg.localServerURL, let observation = kg.observation else {
            return nil
        }

        return .init(
            isUsingLocalServer: true,
            localServerURL: localServerURL,
            observation: .init(
                previewLines: observation.previewLines,
                totalCount: observation.totalCount
            )
        )
    }
}
