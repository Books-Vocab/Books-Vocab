import Foundation

private struct AnySettingsCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int?

    init?(stringValue: String) {
        self.stringValue = stringValue
        self.intValue = nil
    }

    init?(intValue: Int) {
        self.stringValue = "\(intValue)"
        self.intValue = intValue
    }
}

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

        enum CodingKeys: String, CodingKey, CaseIterable {
            case isLoggedIn
            case userInitials
            case avatarURL
            case displayName
            case email
            case authError
            case isAuthenticating
            case iconBreathing
            case manualLoginHint
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings auth"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings auth")
            isLoggedIn = try container.decode(Bool.self, forKey: .isLoggedIn)
            userInitials = try container.decodeIfPresent(String.self, forKey: .userInitials)
            avatarURL = try container.decodeIfPresent(URL.self, forKey: .avatarURL)
            displayName = try container.decode(String.self, forKey: .displayName)
            email = try container.decodeIfPresent(String.self, forKey: .email)
            authError = try container.decodeIfPresent(String.self, forKey: .authError)
            isAuthenticating = try container.decode(Bool.self, forKey: .isAuthenticating)
            iconBreathing = try container.decode(Bool.self, forKey: .iconBreathing)
            manualLoginHint = try container.decodeIfPresent(String.self, forKey: .manualLoginHint)
        }
    }

    struct KG: Codable {
        struct Observation: Codable {
            let previewLines: [String]
            let totalCount: Int

            enum CodingKeys: String, CodingKey, CaseIterable {
                case previewLines
                case totalCount
            }

            init(from decoder: Decoder) throws {
                try SettingsFixtureSeed.rejectUnknownKeys(
                    from: decoder,
                    keys: CodingKeys.allCases,
                    context: "UI World settings KG observation"
                )
                let container = try decoder.container(keyedBy: CodingKeys.self)
                try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings KG observation")
                previewLines = try container.decode([String].self, forKey: .previewLines)
                totalCount = try container.decode(Int.self, forKey: .totalCount)
            }
        }

        let serverURL: String
        let isConnected: Bool
        let connectionPulse: Bool
        let serverCardCount: Int
        let lastSyncDescription: String?
        let isUsingLocalServer: Bool
        let localServerURL: String?
        let observation: Observation?

        enum CodingKeys: String, CodingKey, CaseIterable {
            case serverURL
            case isConnected
            case connectionPulse
            case serverCardCount
            case lastSyncDescription
            case isUsingLocalServer
            case localServerURL
            case observation
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings KG"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings KG")
            serverURL = try container.decode(String.self, forKey: .serverURL)
            isConnected = try container.decode(Bool.self, forKey: .isConnected)
            connectionPulse = try container.decode(Bool.self, forKey: .connectionPulse)
            serverCardCount = try container.decode(Int.self, forKey: .serverCardCount)
            lastSyncDescription = try container.decodeIfPresent(String.self, forKey: .lastSyncDescription)
            isUsingLocalServer = try container.decode(Bool.self, forKey: .isUsingLocalServer)
            localServerURL = try container.decodeIfPresent(String.self, forKey: .localServerURL)
            observation = try container.decodeIfPresent(Observation.self, forKey: .observation)
        }
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

        enum CodingKeys: String, CodingKey, CaseIterable {
            case isActive
            case planName
            case badgeText
            case badgeTone
            case summary
            case detail
            case sourceLabel
            case managementNote
            case pricingUnavailableMessage
            case restoreLabel
            case restoreDescription
            case isRestoreAvailable
            case ctaTitle
            case isRefreshing
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings subscription"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings subscription")
            isActive = try container.decode(Bool.self, forKey: .isActive)
            planName = try container.decode(String.self, forKey: .planName)
            badgeText = try container.decode(String.self, forKey: .badgeText)
            badgeTone = try container.decode(SubscriptionBadgeTone.self, forKey: .badgeTone)
            summary = try container.decode(String.self, forKey: .summary)
            detail = try container.decode(String.self, forKey: .detail)
            sourceLabel = try container.decode(String.self, forKey: .sourceLabel)
            managementNote = try container.decode(String.self, forKey: .managementNote)
            pricingUnavailableMessage = try container.decodeIfPresent(String.self, forKey: .pricingUnavailableMessage)
            restoreLabel = try container.decode(String.self, forKey: .restoreLabel)
            restoreDescription = try container.decode(String.self, forKey: .restoreDescription)
            isRestoreAvailable = try container.decode(Bool.self, forKey: .isRestoreAvailable)
            ctaTitle = try container.decode(String.self, forKey: .ctaTitle)
            isRefreshing = try container.decode(Bool.self, forKey: .isRefreshing)
        }
    }

    struct Preferences: Codable {
        let selectedLanguage: String
        let selectedAppearance: String
        let translationSource: String
        let translationTarget: String
        let selectedReviewMode: String
        let autoSyncEnabled: Bool
        let showAutoSync: Bool

        enum CodingKeys: String, CodingKey, CaseIterable {
            case selectedLanguage
            case selectedAppearance
            case translationSource
            case translationTarget
            case selectedReviewMode
            case autoSyncEnabled
            case showAutoSync
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings preferences"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings preferences")
            selectedLanguage = try container.decode(String.self, forKey: .selectedLanguage)
            selectedAppearance = try container.decode(String.self, forKey: .selectedAppearance)
            translationSource = try container.decode(String.self, forKey: .translationSource)
            translationTarget = try container.decode(String.self, forKey: .translationTarget)
            selectedReviewMode = try container.decode(String.self, forKey: .selectedReviewMode)
            autoSyncEnabled = try container.decode(Bool.self, forKey: .autoSyncEnabled)
            showAutoSync = try container.decode(Bool.self, forKey: .showAutoSync)
        }
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

        enum CodingKeys: String, CodingKey, CaseIterable {
            case mode
            case customInitialIntervalHours
            case customRememberedMultiplier
            case customForgotMultiplier
            case customMinimumIntervalHours
            case customMaximumIntervalHours
            case isProgressPaused
            case progressPausedAt
            case autoplaySpeed
            case autoplaySoundEnabled
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings reviewSettings"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings reviewSettings")
            mode = try container.decode(String.self, forKey: .mode)
            customInitialIntervalHours = try container.decode(Double.self, forKey: .customInitialIntervalHours)
            customRememberedMultiplier = try container.decode(Double.self, forKey: .customRememberedMultiplier)
            customForgotMultiplier = try container.decode(Double.self, forKey: .customForgotMultiplier)
            customMinimumIntervalHours = try container.decode(Double.self, forKey: .customMinimumIntervalHours)
            customMaximumIntervalHours = try container.decode(Double.self, forKey: .customMaximumIntervalHours)
            isProgressPaused = try container.decode(Bool.self, forKey: .isProgressPaused)
            progressPausedAt = try container.decodeIfPresent(Date.self, forKey: .progressPausedAt)
            autoplaySpeed = try container.decode(String.self, forKey: .autoplaySpeed)
            autoplaySoundEnabled = try container.decode(Bool.self, forKey: .autoplaySoundEnabled)
        }
    }

    struct SyncSummary: Codable {
        let isConnected: Bool
        let isSyncing: Bool
        let summaryText: String
        /// Nullable, but the key must still be declared — the seed's contract is
        /// that every field is explicit, so a new presenter field cannot drift
        /// out of the fixture surface unnoticed.
        let lastSyncedText: String?

        enum CodingKeys: String, CodingKey, CaseIterable {
            case isConnected
            case isSyncing
            case summaryText
            case lastSyncedText
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings syncSummary"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings syncSummary")
            isConnected = try container.decode(Bool.self, forKey: .isConnected)
            isSyncing = try container.decode(Bool.self, forKey: .isSyncing)
            summaryText = try container.decode(String.self, forKey: .summaryText)
            lastSyncedText = try container.decodeIfPresent(String.self, forKey: .lastSyncedText)
        }
    }

    struct About: Codable {
        let version: String
        let developerName: String

        enum CodingKeys: String, CodingKey, CaseIterable {
            case version
            case developerName
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings about"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings about")
            version = try container.decode(String.self, forKey: .version)
            developerName = try container.decode(String.self, forKey: .developerName)
        }
    }

    struct Danger: Codable {
        let isDeletingAccount: Bool

        enum CodingKeys: String, CodingKey, CaseIterable {
            case isDeletingAccount
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings danger"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings danger")
            isDeletingAccount = try container.decode(Bool.self, forKey: .isDeletingAccount)
        }
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

        enum CodingKeys: String, CodingKey, CaseIterable {
            case text
            case detail
            case tone
        }

        init(from decoder: Decoder) throws {
            try SettingsFixtureSeed.rejectUnknownKeys(
                from: decoder,
                keys: CodingKeys.allCases,
                context: "UI World settings bookSync"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try SettingsFixtureSeed.requireAllKeys(in: container, context: "UI World settings bookSync")
            text = try container.decode(String.self, forKey: .text)
            detail = try container.decodeIfPresent(String.self, forKey: .detail)
            tone = try container.decode(Tone.self, forKey: .tone)
        }
    }

    let auth: Auth
    let authFixtureRef: String
    let entitlementsFixtureRef: String?
    let preferences: Preferences
    let reviewSettings: Review?
    let kg: KG?
    let subscription: Subscription?
    let syncSummary: SyncSummary?
    let bookSync: BookSync?
    let about: About
    let danger: Danger?
    let manualLoginUserId: String?
    let debugLocalServerURL: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case auth
        case authFixtureRef
        case entitlementsFixtureRef
        case preferences
        case reviewSettings
        case kg
        case subscription
        case syncSummary
        case bookSync
        case about
        case danger
        case manualLoginUserId
        case debugLocalServerURL
    }

    init(from decoder: Decoder) throws {
        try Self.rejectUnknownKeys(
            from: decoder,
            keys: CodingKeys.allCases,
            context: "UI World settings seed"
        )
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try Self.requireAllKeys(in: container, context: "UI World settings seed")
        auth = try container.decode(Auth.self, forKey: .auth)
        authFixtureRef = try container.decode(String.self, forKey: .authFixtureRef)
        entitlementsFixtureRef = try container.decodeIfPresent(String.self, forKey: .entitlementsFixtureRef)
        guard !authFixtureRef.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw DecodingError.dataCorruptedError(
                forKey: .authFixtureRef,
                in: container,
                debugDescription: "UI World settings seed authFixtureRef must not be empty"
            )
        }
        if let entitlementsFixtureRef {
            guard !entitlementsFixtureRef.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw DecodingError.dataCorruptedError(
                    forKey: .entitlementsFixtureRef,
                    in: container,
                    debugDescription: "UI World settings seed entitlementsFixtureRef must be null or non-empty"
                )
            }
        }
        preferences = try container.decode(Preferences.self, forKey: .preferences)
        reviewSettings = try container.decodeIfPresent(Review.self, forKey: .reviewSettings)
        kg = try container.decodeIfPresent(KG.self, forKey: .kg)
        subscription = try container.decodeIfPresent(Subscription.self, forKey: .subscription)
        syncSummary = try container.decodeIfPresent(SyncSummary.self, forKey: .syncSummary)
        bookSync = try container.decodeIfPresent(BookSync.self, forKey: .bookSync)
        about = try container.decode(About.self, forKey: .about)
        danger = try container.decodeIfPresent(Danger.self, forKey: .danger)
        manualLoginUserId = try container.decodeIfPresent(String.self, forKey: .manualLoginUserId)
        debugLocalServerURL = try container.decodeIfPresent(String.self, forKey: .debugLocalServerURL)
    }

    private static func requireAllKeys<C: KeyedDecodingContainerProtocol>(
        in container: C,
        context: String
    ) throws where C.Key: CaseIterable & RawRepresentable, C.Key.RawValue == String {
        for key in C.Key.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "\(context) must explicitly declare \(key.rawValue), even when null"
                )
            )
        }
    }

    private static func rejectUnknownKeys<K: CodingKey & RawRepresentable>(
        from decoder: Decoder,
        keys: [K],
        context: String
    ) throws where K.RawValue == String {
        let rawContainer = try decoder.container(keyedBy: AnySettingsCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(keys.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "\(context) contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
    }
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
                .init(
                    isConnected: $0.isConnected,
                    isSyncing: $0.isSyncing,
                    summaryText: $0.summaryText,
                    lastSyncedText: $0.lastSyncedText
                )
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
