import Foundation
import CryptoKit

/// A one-way identity seam for exact-account UI evidence. The raw reviewer
/// username never enters an accessibility identifier or test log.
enum AccountIdentityFingerprint {
    static func sha256(_ identity: String?) -> String? {
        guard let identity else { return nil }
        let normalized = identity
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .precomposedStringWithCanonicalMapping
            .lowercased(with: Locale(identifier: "en_US_POSIX"))
        guard !normalized.isEmpty else { return nil }
        return SHA256.hash(data: Data(normalized.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}

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
        var identityFingerprint: String? = nil
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
        // 預設值讓既有建構處(fixtures / scenarios)免改;登入才顯示(語意在後端 pipeline)。
        var autoLinkEnabled: Bool = true
        var showAutoLink: Bool = false
        var soundFeedbackEnabled: Bool = false
        var hapticFeedbackEnabled: Bool = true
    }

    struct SyncSummaryState {
        let isConnected: Bool
        let isSyncing: Bool
        let summaryText: String
    }

    /// CloudKit 書庫同步狀態列（CloudKitMirroringMonitor.phase 的 UI 投影）。
    /// 書庫綁 Apple ID 不綁 app 帳號 — 顯示與登入無關；nil = 整列隱藏
    /// （localOnly：container 沒接 CloudKit，顯示同步狀態是誤導）。
    struct BookSyncState: Equatable {
        enum Tone {
            case progress
            case success
            case warning
        }

        let text: String
        /// failed 時的錯誤描述（observability 要求可見，與 monitor 契約一致）。
        let detail: String?
        let tone: Tone
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
    // 預設值讓既有建構處(fixtures / scenarios)免改。
    var bookSync: BookSyncState? = nil
    let about: AboutSection
    let danger: DangerSection?
}

extension SettingsPresenterState.BookSyncState {
    static func from(phase: CloudKitMirroringMonitor.Phase) -> SettingsPresenterState.BookSyncState? {
        switch phase {
        case .localOnly:
            return nil
        case .waitingFirstEvent:
            return .init(text: L10n.string("確認中…"), detail: nil, tone: .progress)
        case .restoring:
            return .init(text: L10n.string("還原中…"), detail: nil, tone: .progress)
        case .failed(let message):
            // 空字串 normalize 成 nil，避免渲染空 caption 行
            //（monitor 端有 fallback 文案，此為防禦線）。
            return .init(
                text: L10n.string("同步異常"),
                detail: message.isEmpty ? nil : message,
                tone: .warning
            )
        case .settled:
            return .init(text: L10n.string("已同步"), detail: nil, tone: .success)
        }
    }
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
    // 預設 no-op 讓既有建構處(preview / scenarios)免改。
    var toggleAutoLink: (Bool) -> Void = { _ in }
    var toggleSoundFeedback: (Bool) -> Void = { _ in }
    var toggleHapticFeedback: (Bool) -> Void = { _ in }
}
