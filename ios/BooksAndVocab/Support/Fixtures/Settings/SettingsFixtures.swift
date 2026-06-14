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

    struct Review: Codable {
        let mode: String
        let customInitialIntervalHours: Double
        let customRememberedMultiplier: Double
        let customForgotMultiplier: Double
        let customMinimumIntervalHours: Double
        let customMaximumIntervalHours: Double
        let isProgressPaused: Bool
        let progressPausedAt: Date?
        let autoplaySpeed: String
        let autoplaySoundEnabled: Bool
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
    // var + default：UI World-owned review settings slice, optional for settings seeds
    // that do not render SettingsReviewSection.
    var reviewSettings: Review? = nil
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

    private static let registry = FixtureRegistry<SettingsFixtureSeed>(
        SettingsFixtureID.allCases.map { fixtureID in
            FixtureRecipe(key: fixtureID.key, surfaces: sharedSurfaces, tags: tags(for: fixtureID)) {
                FixtureDatasetStore.requireSettingsSeed(for: fixtureID)
            }
        }
    )

    private static func tags(for fixtureID: SettingsFixtureID) -> Set<String> {
        switch fixtureID {
        case .loggedOut, .subscribedActive, .subscriptionFree, .subscriptionLoading:
            return ["baseline"]
        case .accountLoggedOutError, .accountLongIdentity, .deletingAccount, .pricingUnavailable:
            return ["edge"]
        case .preferencesAutoSyncOff, .preferencesLoggedOutNoSync:
            return ["preferences"]
        case .debugBackendLocal:
            return ["debug"]
        }
    }

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<SettingsFixtureSeed>] {
        registry.recipes(for: surface)
    }

    static func state(for fixtureID: SettingsFixtureID) -> SettingsPresenterState {
        renderModel(for: fixtureID).state
    }

    static func reviewSettings(for fixtureID: SettingsFixtureID) -> ReviewSettings {
        let seed = FixtureDatasetStore.requireSettingsSeed(for: fixtureID)
        guard let review = seed.reviewSettings else {
            preconditionFailure("UI World settings.\(fixtureID.rawValue) must declare reviewSettings")
        }
        return SettingsFixtureAdapter.makeReviewSettings(from: review, fixtureID: fixtureID)
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
    static func makeReviewSettings(from seed: SettingsFixtureSeed.Review, fixtureID: SettingsFixtureID) -> ReviewSettings {
        guard let mode = ReviewSettingsMode(rawValue: seed.mode) else {
            preconditionFailure("UI World settings.\(fixtureID.rawValue).reviewSettings has unknown mode \(seed.mode)")
        }
        guard let autoplaySpeed = AutoplaySpeed(rawValue: seed.autoplaySpeed) else {
            preconditionFailure("UI World settings.\(fixtureID.rawValue).reviewSettings has unknown autoplaySpeed \(seed.autoplaySpeed)")
        }
        return ReviewSettings(
            mode: mode,
            customInitialIntervalHours: seed.customInitialIntervalHours,
            customRememberedMultiplier: seed.customRememberedMultiplier,
            customForgotMultiplier: seed.customForgotMultiplier,
            customMinimumIntervalHours: seed.customMinimumIntervalHours,
            customMaximumIntervalHours: seed.customMaximumIntervalHours,
            isProgressPaused: seed.isProgressPaused,
            progressPausedAt: seed.progressPausedAt,
            autoplaySpeed: autoplaySpeed,
            autoplaySoundEnabled: seed.autoplaySoundEnabled
        )
    }

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
