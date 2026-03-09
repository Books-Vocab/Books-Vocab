import Foundation

struct SettingsPresenterState {
    struct AuthSection {
        let isLoggedIn: Bool
        let userInitials: String?
        let avatarURL: URL?
        let displayName: String
        let email: String?
        let authError: String?
        let iconBreathing: Bool
        let isDeveloper: Bool
        let debug: DebugAuthSection?
    }

    struct DebugAuthSection {
        let developerAccountId: String
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
        let ctaTitle: String
        let isRefreshing: Bool
    }

    struct OptionalIntegrationSection {
        let isEnabled: Bool
    }

    struct AboutSection {
        let version: String
        let developerName: String
        let developerAccountId: String?
    }

    struct DangerSection {
        let isDeletingAccount: Bool
    }

    let auth: AuthSection
    let kg: KGSection?
    let subscription: SubscriptionSection?
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
    let setDeveloperAccount: () -> Void
    let clearDeveloperAccount: () -> Void
    let useProductionBackend: () -> Void
    let useLocalBackend: () -> Void
    let showSubscriptionPaywall: () -> Void
    let showOptionalIntegrationInfo: () -> Void
    let requestDeleteAccount: () -> Void
}
