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
        struct DebugSection {
            let isUsingLocalServer: Bool
            let localServerURL: String
        }

        let serverURL: String
        let isConnected: Bool
        let connectionPulse: Bool
        let serverCardCount: Int
        let lastSyncDescription: String?
        let debug: DebugSection?
    }

    struct SubscriptionSection {
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
    }

    struct SyncSummaryState {
        let isConnected: Bool
        let summaryText: String
    }

    struct OptionalIntegrationSection {
        let isEnabled: Bool
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
    let optionalIntegration: OptionalIntegrationSection?
    let about: AboutSection
    let danger: DangerSection?
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
    let showOptionalIntegrationInfo: () -> Void
    let requestDeleteAccount: () -> Void
    let openPrivacyPolicy: () -> Void
    let openSupport: () -> Void
    let requestAppRating: () -> Void
}
