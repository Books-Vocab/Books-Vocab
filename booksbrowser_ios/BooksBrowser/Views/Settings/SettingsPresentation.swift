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
        let serverURL: String
        let isConnected: Bool
        let connectionPulse: Bool
        let serverCardCount: Int
        let lastSyncDescription: String?
    }

    struct MochiSection {
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
    let mochi: MochiSection?
    let about: AboutSection
    let danger: DangerSection?
}

struct SettingsPresenterActions {
    let dismiss: () -> Void
    let loginWithGoogle: () -> Void
    let loginWithApple: () -> Void
    let logout: () -> Void
    let manualLogin: () -> Void
    let setDeveloperAccount: () -> Void
    let clearDeveloperAccount: () -> Void
    let showMochiInfo: () -> Void
    let requestDeleteAccount: () -> Void
}
