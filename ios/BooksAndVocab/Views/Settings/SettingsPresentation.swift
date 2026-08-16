import Foundation
import CryptoKit

enum SettingsSyncDataOutcome: String, Codable, Equatable {
    case none
    case partial
    case complete
}

struct SettingsSyncTransportEvent: Equatable, Sendable {
    let round: Int
    let path: String
    let statusCode: Int

    var marker: String {
        "round=\(round),path=\(path),status=\(statusCode)"
    }
}

struct SettingsSyncPerfRecord: Equatable, Sendable {
    let label: String
    let detail: String

    var marker: String {
        "\(label){\(detail)}"
    }
}

struct SettingsSyncLifecycleEvidence: Equatable {
    let lifecycle: String
    let attempt: Int
    let dataOutcome: SettingsSyncDataOutcome
    let residualWords: [String]
    let readBackWords: [String]
    let transportEvents: [SettingsSyncTransportEvent]
    let perfMarks: [SettingsSyncPerfRecord]

    /// DEBUG-only accessibility payload. Every field is produced by the real
    /// transport/model path; it is not a test-controlled phase or counter.
    var marker: String {
        let residual = residualWords.isEmpty ? "-" : residualWords.joined(separator: ",")
        let readBack = readBackWords.isEmpty ? "-" : readBackWords.joined(separator: ",")
        let stableTransportEvents = transportEvents.sorted { lhs, rhs in
            if lhs.round != rhs.round { return lhs.round < rhs.round }
            if lhs.path != rhs.path { return lhs.path < rhs.path }
            return lhs.statusCode < rhs.statusCode
        }
        let transport = stableTransportEvents.isEmpty
            ? "-"
            : stableTransportEvents.map(\.marker).joined(separator: "|")
        let perf = perfMarks.isEmpty
            ? "-"
            : perfMarks.map(\.marker).joined(separator: "|")
        return [
            "schema=settings.sync.evidence.v1",
            "lifecycle=\(lifecycle)",
            "attempt=\(attempt)",
            "dataOutcome=\(dataOutcome.rawValue)",
            "residualCount=\(residualWords.count)",
            "residualWords=\(residual)",
            "readBackCount=\(readBackWords.count)",
            "readBackWords=\(readBack)",
            "transportEvents=\(transport)",
            "perfMarks=\(perf)"
        ].joined(separator: ";")
    }
}

enum SettingsSyncFixtureLifecycle: String, Codable, Equatable {
    case idle
    case syncing
    case terminalSuccess
    case terminalError
    case retry
    case dismissed
}

enum SettingsSyncLifecycle: Equatable {
    case idle
    case syncing
    case terminalSuccess
    case terminalError(message: String)
    case retry
    case dismissed

    enum Action: Equatable {
        case begin
        case retry
        case succeed
        case fail(message: String)
        case cancel
        case dismiss
        case reset
    }

    enum TransitionError: Error, Equatable {
        case illegal(state: SettingsSyncLifecycle, action: Action)
    }

    var isInFlight: Bool {
        switch self {
        case .syncing, .retry: return true
        case .idle, .terminalSuccess, .terminalError, .dismissed: return false
        }
    }

    var isTerminal: Bool {
        switch self {
        case .terminalSuccess, .terminalError: return true
        case .idle, .syncing, .retry, .dismissed: return false
        }
    }

    @discardableResult
    mutating func transition(_ action: Action) throws -> SettingsSyncLifecycle {
        let next: SettingsSyncLifecycle
        switch (self, action) {
        case (.idle, .begin), (.terminalSuccess, .begin), (.dismissed, .begin):
            next = .syncing
        case (.terminalError, .retry):
            next = .retry
        case (.syncing, .succeed), (.retry, .succeed):
            next = .terminalSuccess
        case (.syncing, .fail(let message)), (.retry, .fail(let message)):
            next = .terminalError(message: message)
        case (.syncing, .cancel), (.retry, .cancel):
            next = .idle
        case (.terminalSuccess, .dismiss), (.terminalError, .dismiss):
            next = .dismissed
        case (_, .reset):
            next = .idle
        default:
            throw TransitionError.illegal(state: self, action: action)
        }
        self = next
        return next
    }

    mutating func begin() -> Bool {
        do {
            try transition(.begin)
            return true
        } catch {
            return false
        }
    }

    mutating func retry() -> Bool {
        do {
            try transition(.retry)
            return true
        } catch {
            return false
        }
    }

    mutating func succeed() -> Bool {
        do {
            try transition(.succeed)
            return true
        } catch {
            return false
        }
    }

    mutating func fail(message: String) -> Bool {
        do {
            try transition(.fail(message: message))
            return true
        } catch {
            return false
        }
    }

    mutating func cancel() -> Bool {
        do {
            try transition(.cancel)
            return true
        } catch {
            return false
        }
    }

    mutating func dismiss() -> Bool {
        do {
            try transition(.dismiss)
            return true
        } catch {
            return false
        }
    }

    mutating func reset() -> Bool {
        do {
            try transition(.reset)
            return true
        } catch {
            return false
        }
    }
}

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

/// A live settings configuration problem is state, not an implicit fallback.
/// The affected surfaces let the presenter keep account/auth, other settings,
/// and translation failures distinguishable without exposing server errors as
/// user-facing copy.
struct SettingsConfigurationIssue: Equatable {
    enum Surface: String, CaseIterable, Hashable {
        case account
        case other
        case translation
    }

    enum Operation: String, Equatable {
        case fetch
        case save
    }

    let surfaces: Set<Surface>
    let operation: Operation
    let message: String

    var accessibilityValue: String {
        let surfaceIDs = surfaces.map(\.rawValue).sorted().joined(separator: ",")
        return "\(operation.rawValue):\(surfaceIDs)"
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
        let lifecycle: SettingsSyncLifecycle
        /// Connection + card count. Kept to two segments so it fits the row's
        /// single trailing line; anything longer is truncated with no way for
        /// the user to see what was cut.
        let summaryText: String
        /// "Last synced …", rendered on its own line below the row. It used to
        /// be a third segment of `summaryText` and was therefore always the
        /// part that fell off the end.
        let lastSyncedText: String?
        /// Provenance for the current lifecycle round. Legacy callers keep the
        /// zero/none defaults until the UI World schema carries these fields.
        let attempt: Int
        let dataOutcome: SettingsSyncDataOutcome
        let message: String?
        let evidence: SettingsSyncLifecycleEvidence?

        init(
            isConnected: Bool,
            lifecycle: SettingsSyncLifecycle,
            summaryText: String,
            lastSyncedText: String?,
            attempt: Int = 0,
            dataOutcome: SettingsSyncDataOutcome = .none,
            message: String? = nil,
            evidence: SettingsSyncLifecycleEvidence? = nil
        ) {
            self.isConnected = isConnected
            self.lifecycle = lifecycle
            self.summaryText = summaryText
            self.lastSyncedText = lastSyncedText
            self.attempt = attempt
            self.dataOutcome = dataOutcome
            self.message = message
            self.evidence = evidence
        }

        var isSyncing: Bool { lifecycle.isInFlight }
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
        let resetLifecycle: SettingsResetLifecycle?

        init(isDeletingAccount: Bool, resetLifecycle: SettingsResetLifecycle? = nil) {
            self.isDeletingAccount = isDeletingAccount
            self.resetLifecycle = resetLifecycle
        }
    }

    let auth: AuthSection
    let preferences: PreferencesSection
    let kg: KGSection?
    let subscription: SubscriptionSection?
    let syncSummary: SyncSummaryState?
    // 預設值讓既有建構處(fixtures / scenarios)免改。
    var bookSync: BookSyncState? = nil
    /// Persistent, typed state for a live fetch/save failure. The view must not
    /// silently render defaults while this is non-nil.
    var configurationIssue: SettingsConfigurationIssue? = nil
    let about: AboutSection
    let danger: DangerSection?
}

/// Observable boundary for the local-data reset operation. The snapshot pair is
/// intentionally part of the state rather than inferred from the current view:
/// the UI must show what existed before the destructive operation and what the
/// terminal state contains after it completes.
struct SettingsResetLifecycle: Equatable {
    enum Phase: String, Equatable {
        case preReset
        case resetting
        case succeeded
        case failed
    }

    struct Snapshot: Equatable {
        /// `nil` means SwiftData could not prove the count. It is deliberately
        /// distinct from zero: an unreadable store must never look empty.
        let localCardCount: Int?
        let localCardCountError: String?
        let hasCustomPreferences: Bool
        let isLoggedIn: Bool

        init(localCardCount: Int, hasCustomPreferences: Bool, isLoggedIn: Bool) {
            self.localCardCount = localCardCount
            self.localCardCountError = nil
            self.hasCustomPreferences = hasCustomPreferences
            self.isLoggedIn = isLoggedIn
        }

        init(
            unreadableLocalCardCount error: String,
            hasCustomPreferences: Bool,
            isLoggedIn: Bool
        ) {
            self.localCardCount = nil
            self.localCardCountError = error
            self.hasCustomPreferences = hasCustomPreferences
            self.isLoggedIn = isLoggedIn
        }

        var isReadable: Bool {
            localCardCount != nil && localCardCountError == nil
        }

        var isResetComplete: Bool {
            isReadable && localCardCount == 0 && !hasCustomPreferences
        }
    }

    let phase: Phase
    let before: Snapshot
    let after: Snapshot
    let terminalMessage: String?
    let canRetry: Bool

    static func preReset(before: Snapshot) -> Self {
        .init(
            phase: .preReset,
            before: before,
            after: before,
            terminalMessage: before.isReadable
                ? nil
                : L10n.string("無法讀取本機資料，重設已停用。"),
            canRetry: before.isReadable
        )
    }

    func resetting() -> Self {
        .init(
            phase: .resetting,
            before: before,
            after: after,
            terminalMessage: nil,
            canRetry: false
        )
    }

    func succeeded(after: Snapshot, message: String) -> Self {
        .init(
            phase: .succeeded,
            before: before,
            after: after,
            terminalMessage: message,
            canRetry: false
        )
    }

    func failed(after: Snapshot, message: String) -> Self {
        .init(
            phase: .failed,
            before: before,
            after: after,
            terminalMessage: message,
            canRetry: true
        )
    }
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
    var retrySync: () -> Void = {}
    var dismissSyncStatus: () -> Void = {}
    let toggleAutoSync: (Bool) -> Void
    let exportVocabularyCSV: () -> Void
    // 預設 no-op 讓既有建構處(preview / scenarios)免改。
    var toggleAutoLink: (Bool) -> Void = { _ in }
    var toggleSoundFeedback: (Bool) -> Void = { _ in }
    var toggleHapticFeedback: (Bool) -> Void = { _ in }
    var resetLocalData: () -> Void = {}
}
