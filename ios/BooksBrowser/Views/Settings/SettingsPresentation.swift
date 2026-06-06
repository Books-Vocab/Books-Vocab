import Foundation

struct SettingsPresenterState {
    struct AuthSection {
        let isLoggedIn: Bool
        let userInitials: String?
        let avatarURL: URL?
        let displayName: String
        let email: String?
        let authError: String?
        let isAuthenticating: Bool
        let iconBreathing: Bool
        let debug: DebugAuthSection?
    }

    struct DebugAuthSection {
        let manualLoginHint: String?
    }

    struct KGSection {
        struct ObservationSection {
            let previewLines: [String]
            let totalCount: Int
        }

        struct DebugSection {
            let isUsingLocalServer: Bool
            let localServerURL: String
            let observation: ObservationSection
        }

        let serverURL: String
        let isConnected: Bool
        let connectionPulse: Bool
        let serverCardCount: Int
        let lastSyncDescription: String?
        let debug: DebugSection?
    }

    struct SubscriptionSection {
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

    struct PreferencesSection {
        let selectedLanguage: String
        let selectedAppearance: String
        let translationSource: String
        let translationTarget: String
        let selectedReviewMode: String
        let autoSyncEnabled: Bool
        let showAutoSync: Bool
    }

    struct SyncSummaryState {
        let isConnected: Bool
        let isSyncing: Bool
        let summaryText: String
    }

    struct AboutSection {
        let version: String
        let developerName: String
    }

    struct DangerSection {
        let isDeletingAccount: Bool
    }

    let auth: AuthSection
    let preferences: PreferencesSection
    let kg: KGSection?
    let subscription: SubscriptionSection?
    let syncSummary: SyncSummaryState?
    let about: AboutSection
    let danger: DangerSection?
}

extension SettingsPresenterState.PreferencesSection {
    static func reviewModeDisplayName(for settings: ReviewSettings) -> String {
        let modeDisplayName = settings.mode.displayName
        guard settings.isProgressPaused else { return modeDisplayName }
        return L10n.format("已凍結 · %@", modeDisplayName)
    }
}

enum SubscriptionBadgeTone {
    case neutral
    case accent
    case success
}

struct SettingsPresenterActions {
    let dismiss: () -> Void
    let loginWithGoogle: () -> Void
    let loginWithApple: () -> Void
    let logout: () -> Void
    let manualLogin: () -> Void
    let useProductionBackend: () -> Void
    let useLocalBackend: () -> Void
    let selectLanguage: (AppLanguage) -> Void
    let selectAppearance: (AppAppearanceMode) -> Void
    let showSubscriptionPaywall: () -> Void
    let requestDeleteAccount: () -> Void
    let openPrivacyPolicy: () -> Void
    let openTermsOfService: () -> Void
    let openSupport: () -> Void
    let requestAppRating: () -> Void
    let resync: () -> Void
    let toggleAutoSync: (Bool) -> Void
    let exportVocabularyCSV: () -> Void
}
