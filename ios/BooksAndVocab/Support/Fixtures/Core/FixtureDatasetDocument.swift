import Foundation
import CryptoKit


struct AnyCodingKey: CodingKey {
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

struct FixtureDatasetDocument: Decodable {
    static let currentSchema = "kg.fixture.dataset.v2"

    let schema: String
    let datasetID: String
    let assets: UIWorldAssetManifest
    let preferences: UIWorldPreferencesSeed
    let auth: [String: UIWorldAuthSeed]
    let entitlements: [String: UIWorldEntitlementsSeed]
    let settings: [String: SettingsFixtureSeed]
    let bookshelf: [String: BookshelfFixtureSeed]
    let todayReview: [String: TodayReviewSessionSeed]
    let notebook: [String: NotebookFixtureSeed]
    let podcast: [String: PodcastFixtureSeed]
    let runtimePodcast: [String: UIWorldRuntimePodcastSeed]
    let reader: [String: UIWorldReaderSeed]
    let vocabulary: [String: UIWorldVocabularySeed]
    let reviewDeck: [String: UIWorldReviewDeckSeed]
    let syncPresenter: [String: UIWorldSyncPresenterSeed]
    /// Optional cross-domain state for scenarios that need one coherent clock
    /// or content projection. Ordinary UI Worlds may omit it entirely.
    let scenarioContext: UIWorldScenarioContextSeed?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case schema
        case datasetID
        case assets
        case preferences
        case auth
        case entitlements
        case settings
        case bookshelf
        case todayReview
        case notebook
        case podcast
        case runtimePodcast
        case reader
        case vocabulary
        case reviewDeck
        case syncPresenter
        case scenarioContext
    }

    /// Single source of truth for the top-level key set. Keyed decoding
    /// silently ignores unknown keys, so decode and contract tests diff raw
    /// keys against this to fail loudly on domain-level typos.
    static var knownTopLevelKeys: Set<String> {
        Set(CodingKeys.allCases.map(\.rawValue))
    }

    private static let requiredV2DomainKeys: [CodingKeys] = [
        .assets,
        .preferences,
        .auth,
        .entitlements,
        .settings,
        .bookshelf,
        .todayReview,
        .notebook,
        .podcast,
        .runtimePodcast,
        .reader,
        .vocabulary,
        .reviewDeck,
        .syncPresenter,
    ]

    init(
        schema: String = Self.currentSchema,
        datasetID: String,
        assets: UIWorldAssetManifest = .empty,
        preferences: UIWorldPreferencesSeed = .empty,
        auth: [String: UIWorldAuthSeed] = [:],
        entitlements: [String: UIWorldEntitlementsSeed] = [:],
        settings: [String: SettingsFixtureSeed] = [:],
        bookshelf: [String: BookshelfFixtureSeed] = [:],
        todayReview: [String: TodayReviewSessionSeed] = [:],
        notebook: [String: NotebookFixtureSeed] = [:],
        podcast: [String: PodcastFixtureSeed] = [:],
        runtimePodcast: [String: UIWorldRuntimePodcastSeed] = [:],
        reader: [String: UIWorldReaderSeed] = [:],
        vocabulary: [String: UIWorldVocabularySeed] = [:],
        reviewDeck: [String: UIWorldReviewDeckSeed] = [:],
        syncPresenter: [String: UIWorldSyncPresenterSeed] = [:],
        scenarioContext: UIWorldScenarioContextSeed? = nil
    ) {
        self.schema = schema
        self.datasetID = datasetID
        self.assets = assets
        self.preferences = preferences
        self.auth = auth
        self.entitlements = entitlements
        self.settings = settings
        self.bookshelf = bookshelf
        self.todayReview = todayReview
        self.notebook = notebook
        self.podcast = podcast
        self.runtimePodcast = runtimePodcast
        self.reader = reader
        self.vocabulary = vocabulary
        self.reviewDeck = reviewDeck
        self.syncPresenter = syncPresenter
        self.scenarioContext = scenarioContext
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownTopLevelKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(Self.knownTopLevelKeys)
        guard unknownTopLevelKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World v2 contains unknown top-level keys \(unknownTopLevelKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        schema = try container.decode(String.self, forKey: .schema)
        guard schema == Self.currentSchema else {
            throw DecodingError.dataCorruptedError(
                forKey: .schema,
                in: container,
                debugDescription: "UI World schema must be \(Self.currentSchema), got \(schema)"
            )
        }
        datasetID = try container.decode(String.self, forKey: .datasetID)
        guard !datasetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw DecodingError.dataCorruptedError(
                forKey: .datasetID,
                in: container,
                debugDescription: "UI World datasetID must not be empty"
            )
        }
        for key in Self.requiredV2DomainKeys where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World v2 must explicitly declare top-level \(key.rawValue)"
                )
            )
        }
        assets = try container.decode(UIWorldAssetManifest.self, forKey: .assets)
        preferences = try container.decode(UIWorldPreferencesSeed.self, forKey: .preferences)
        auth = try container.decode([String: UIWorldAuthSeed].self, forKey: .auth)
        entitlements = try container.decode([String: UIWorldEntitlementsSeed].self, forKey: .entitlements)
        settings = try container.decode([String: SettingsFixtureSeed].self, forKey: .settings)
        bookshelf = try container.decode([String: BookshelfFixtureSeed].self, forKey: .bookshelf)
        todayReview = try container.decode([String: TodayReviewSessionSeed].self, forKey: .todayReview)
        notebook = try container.decode([String: NotebookFixtureSeed].self, forKey: .notebook)
        podcast = try container.decode([String: PodcastFixtureSeed].self, forKey: .podcast)
        runtimePodcast = try container.decode([String: UIWorldRuntimePodcastSeed].self, forKey: .runtimePodcast)
        reader = try container.decode([String: UIWorldReaderSeed].self, forKey: .reader)
        vocabulary = try container.decode([String: UIWorldVocabularySeed].self, forKey: .vocabulary)
        reviewDeck = try container.decode([String: UIWorldReviewDeckSeed].self, forKey: .reviewDeck)
        syncPresenter = try container.decode([String: UIWorldSyncPresenterSeed].self, forKey: .syncPresenter)
        // Optional domain: absent (older QA worlds) or present-but-null-clock
        // (checked-in baseline / generated demo) both decode fine.
        scenarioContext = try container.decodeIfPresent(UIWorldScenarioContextSeed.self, forKey: .scenarioContext)

        try validateKnownFixtureIDs(codingPath: container.codingPath)
        try Self.validatePreferenceKeys(preferences, codingPath: container.codingPath)
        try Self.validateAuthSeeds(auth, codingPath: container.codingPath)
        try Self.validateSettingsStateReferences(settings, auth: auth, entitlements: entitlements, codingPath: container.codingPath)
        try Self.validateSwiftDataRowState(
            reader: reader,
            notebook: notebook,
            vocabulary: vocabulary,
            reviewDeck: reviewDeck,
            codingPath: container.codingPath
        )
        try Self.validateRuntimePodcastAssetReferences(runtimePodcast, assets: assets, codingPath: container.codingPath)
        try Self.validateReaderAssetReferences(reader, assets: assets, codingPath: container.codingPath)
        try Self.validateBookshelfAssetReferences(bookshelf, assets: assets, codingPath: container.codingPath)
    }

    private func validateKnownFixtureIDs(codingPath: [CodingKey]) throws {
        try Self.validateKnownKeys(settings.keys, SettingsFixtureID.self, domain: "settings", codingPath: codingPath)
        try Self.validateKnownKeys(auth.keys, UIWorldAuthFixtureID.self, domain: "auth", codingPath: codingPath)
        try Self.validateKnownKeys(entitlements.keys, UIWorldEntitlementsFixtureID.self, domain: "entitlements", codingPath: codingPath)
        try Self.validateKnownKeys(bookshelf.keys, BookshelfFixtureID.self, domain: "bookshelf", codingPath: codingPath)
        try Self.validateKnownKeys(todayReview.keys, TodayReviewFixtureID.self, domain: "todayReview", codingPath: codingPath)
        try Self.validateKnownKeys(notebook.keys, NotebookFixtureID.self, domain: "notebook", codingPath: codingPath)
        try Self.validateKnownKeys(podcast.keys, PodcastFixtureID.self, domain: "podcast", codingPath: codingPath)
        try Self.validateKnownKeys(runtimePodcast.keys, UIWorldRuntimePodcastFixtureID.self, domain: "runtimePodcast", codingPath: codingPath)
        try Self.validateKnownKeys(reader.keys, UIWorldReaderFixtureID.self, domain: "reader", codingPath: codingPath)
        try Self.validateKnownKeys(vocabulary.keys, UIWorldVocabularyFixtureID.self, domain: "vocabulary", codingPath: codingPath)
        try Self.validateKnownKeys(reviewDeck.keys, UIWorldReviewDeckFixtureID.self, domain: "reviewDeck", codingPath: codingPath)
        try Self.validateKnownKeys(syncPresenter.keys, UIWorldSyncPresenterFixtureID.self, domain: "syncPresenter", codingPath: codingPath)
    }

    private static func validateKnownKeys<ID: RawRepresentable & CaseIterable>(
        _ keys: some Sequence<String>,
        _ idType: ID.Type,
        domain: String,
        codingPath: [CodingKey]
    ) throws where ID.RawValue == String {
        let known = Set(idType.allCases.map(\.rawValue))
        let unknown = Set(keys).subtracting(known)
        guard unknown.isEmpty else {
            throw dataCorrupted(
                "UI World domain \(domain) contains unknown fixture IDs \(unknown.sorted())",
                codingPath: codingPath
            )
        }
    }

    private static func validatePreferenceKeys(
        _ preferences: UIWorldPreferencesSeed,
        codingPath: [CodingKey]
    ) throws {
        try validatePreferenceKeys(
            preferences.userDefaults.keys,
            domain: "preferences.userDefaults",
            allowed: UIWorldPreferencesSeed.userDefaultsKeys,
            codingPath: codingPath
        )
        try validatePreferenceKeys(
            preferences.ubiquitousKeyValueStore.keys,
            domain: "preferences.ubiquitousKeyValueStore",
            allowed: UIWorldPreferencesSeed.ubiquitousKeyValueStoreKeys,
            codingPath: codingPath
        )
    }

    private static func validatePreferenceKeys(
        _ keys: some Sequence<String>,
        domain: String,
        allowed: Set<String>,
        codingPath: [CodingKey]
    ) throws {
        for key in keys where key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw dataCorrupted("UI World \(domain) contains an empty key", codingPath: codingPath)
        }
        let unknown = Set(keys).subtracting(allowed)
        guard unknown.isEmpty else {
            throw dataCorrupted(
                "UI World \(domain) contains unknown app preference keys \(unknown.sorted())",
                codingPath: codingPath
            )
        }
    }

    private static func validateAuthSeeds(
        _ seeds: [String: UIWorldAuthSeed],
        codingPath: [CodingKey]
    ) throws {
        for (fixtureID, seed) in seeds {
            let owner = "auth.\(fixtureID)"
            switch seed.keychainTokenState {
            case .available:
                guard seed.isLoggedIn else {
                    throw dataCorrupted("\(owner) keychainTokenState=available requires isLoggedIn=true", codingPath: codingPath)
                }
                guard seed.token?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else {
                    throw dataCorrupted("\(owner) keychainTokenState=available requires a non-empty token", codingPath: codingPath)
                }
            case .readFailed:
                guard seed.isLoggedIn else {
                    throw dataCorrupted("\(owner) keychainTokenState=readFailed requires isLoggedIn=true", codingPath: codingPath)
                }
                guard seed.userId?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else {
                    throw dataCorrupted("\(owner) keychainTokenState=readFailed requires a persisted userId", codingPath: codingPath)
                }
                guard seed.token == nil else {
                    throw dataCorrupted("\(owner) keychainTokenState=readFailed must not expose a readable token", codingPath: codingPath)
                }
            case .absent:
                guard !seed.isLoggedIn else {
                    throw dataCorrupted("\(owner) keychainTokenState=absent requires isLoggedIn=false", codingPath: codingPath)
                }
                guard seed.token == nil else {
                    throw dataCorrupted("\(owner) keychainTokenState=absent must not include token", codingPath: codingPath)
                }
            }

            if seed.isLoggedIn {
                guard seed.userId?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else {
                    throw dataCorrupted("\(owner) logged-in seed requires a non-empty userId", codingPath: codingPath)
                }
                guard !seed.isAuthenticating else {
                    throw dataCorrupted("\(owner) logged-in seed must not also be authenticating", codingPath: codingPath)
                }
                guard seed.authError == nil else {
                    throw dataCorrupted("\(owner) logged-in seed must not carry authError", codingPath: codingPath)
                }
            }
        }
    }

    private static func validateSettingsStateReferences(
        _ seeds: [String: SettingsFixtureSeed],
        auth: [String: UIWorldAuthSeed],
        entitlements: [String: UIWorldEntitlementsSeed],
        codingPath: [CodingKey]
    ) throws {
        for (fixtureID, seed) in seeds {
            let owner = "settings.\(fixtureID)"
            let authRef = seed.authFixtureRef.trimmingCharacters(in: .whitespacesAndNewlines)
            guard authRef.hasPrefix("auth.") else {
                throw dataCorrupted("\(owner).authFixtureRef must point into auth.*, got \(authRef)", codingPath: codingPath)
            }
            let authKey = String(authRef.dropFirst("auth.".count))
            guard let authSeed = auth[authKey] else {
                throw dataCorrupted("\(owner).authFixtureRef references missing \(authRef)", codingPath: codingPath)
            }
            guard seed.auth.isLoggedIn == authSeed.isLoggedIn else {
                throw dataCorrupted("\(owner).auth.isLoggedIn must match \(authRef).isLoggedIn", codingPath: codingPath)
            }
            guard seed.auth.authError == authSeed.authError else {
                throw dataCorrupted("\(owner).auth.authError must match \(authRef).authError", codingPath: codingPath)
            }
            if seed.auth.isLoggedIn {
                guard seed.auth.email == authSeed.email else {
                    throw dataCorrupted("\(owner).auth.email must match \(authRef).email", codingPath: codingPath)
                }
                guard seed.auth.displayName == authSeed.displayName else {
                    throw dataCorrupted("\(owner).auth.displayName must match \(authRef).displayName", codingPath: codingPath)
                }
            }

            if let entitlementsRef = seed.entitlementsFixtureRef?.trimmingCharacters(in: .whitespacesAndNewlines) {
                guard entitlementsRef.hasPrefix("entitlements.") else {
                    throw dataCorrupted("\(owner).entitlementsFixtureRef must point into entitlements.*, got \(entitlementsRef)", codingPath: codingPath)
                }
                let entitlementsKey = String(entitlementsRef.dropFirst("entitlements.".count))
                guard let entitlementsSeed = entitlements[entitlementsKey] else {
                    throw dataCorrupted("\(owner).entitlementsFixtureRef references missing \(entitlementsRef)", codingPath: codingPath)
                }
                if let subscription = seed.subscription, !subscription.isRefreshing {
                    guard subscription.isActive == entitlementsSeed.pro.is_active else {
                        throw dataCorrupted("\(owner).subscription.isActive must match \(entitlementsRef).pro.is_active", codingPath: codingPath)
                    }
                }
            } else {
                guard seed.subscription == nil else {
                    throw dataCorrupted("\(owner) without entitlementsFixtureRef must not declare subscription UI state", codingPath: codingPath)
                }
            }
        }
    }

    private static func validateSwiftDataRowState(
        reader: [String: UIWorldReaderSeed],
        notebook: [String: NotebookFixtureSeed],
        vocabulary: [String: UIWorldVocabularySeed],
        reviewDeck: [String: UIWorldReviewDeckSeed],
        codingPath: [CodingKey]
    ) throws {
        for (fixtureID, seed) in reader {
            try validateNotebookSyncStatus(
                seed.notebookSyncStatus,
                owner: "reader.\(fixtureID).notebookSyncStatus",
                codingPath: codingPath
            )
            try validateVocabularyEntryRowState(
                syncStatus: seed.entry.syncStatus,
                actionType: seed.entry.actionType,
                owner: "reader.\(fixtureID).entry.\(seed.entry.word)",
                codingPath: codingPath
            )
        }

        for (fixtureID, seed) in notebook {
            let notebookIDs = seed.notebooks.map(\.remoteId)
            try validateUniqueValues(
                notebookIDs,
                owner: "notebook.\(fixtureID).notebooks.remoteId",
                codingPath: codingPath
            )
            for notebook in seed.notebooks {
                try validateNotebookSyncStatus(
                    notebook.syncStatus,
                    owner: "notebook.\(fixtureID).\(notebook.remoteId).syncStatus",
                    codingPath: codingPath
                )
                for entry in notebook.entries {
                    try validateVocabularyEntryRowState(
                        syncStatus: entry.syncStatus,
                        actionType: entry.actionType,
                        owner: "notebook.\(fixtureID).\(notebook.remoteId).entry.\(entry.word)",
                        codingPath: codingPath
                    )
                }
            }
        }

        for (fixtureID, seed) in vocabulary {
            try validateNotebookSyncStatus(
                seed.notebookSyncStatus,
                owner: "vocabulary.\(fixtureID).notebookSyncStatus",
                codingPath: codingPath
            )
            let words = seed.entries.map(\.word)
            try validateUniqueValues(
                words,
                owner: "vocabulary.\(fixtureID).entries.word",
                codingPath: codingPath
            )
            let entryWords = Set(words)
            for entry in seed.entries {
                try validateVocabularyEntryRowState(
                    syncStatus: entry.syncStatus,
                    actionType: entry.actionType,
                    owner: "vocabulary.\(fixtureID).entry.\(entry.word)",
                    codingPath: codingPath
                )
            }
            for record in seed.reviewHistory where !entryWords.contains(record.word) {
                throw dataCorrupted(
                    "vocabulary.\(fixtureID).reviewHistory.\(record.word) must reference an entry in the same seed",
                    codingPath: codingPath
                )
            }
        }

        for (fixtureID, seed) in reviewDeck {
            try validateNotebookSyncStatus(
                seed.notebookSyncStatus,
                owner: "reviewDeck.\(fixtureID).notebookSyncStatus",
                codingPath: codingPath
            )
            try validateUniqueValues(
                seed.entries.map(\.word),
                owner: "reviewDeck.\(fixtureID).entries.word",
                codingPath: codingPath
            )
            for entry in seed.entries {
                try validateVocabularyEntryRowState(
                    syncStatus: entry.syncStatus,
                    actionType: entry.actionType,
                    owner: "reviewDeck.\(fixtureID).entry.\(entry.word)",
                    codingPath: codingPath
                )
            }
        }
    }

    private static func validateNotebookSyncStatus(
        _ syncStatus: Int,
        owner: String,
        codingPath: [CodingKey]
    ) throws {
        guard [0, 1].contains(syncStatus) else {
            throw dataCorrupted("\(owner) must be valid Notebook.syncStatus (0=pending, 1=synced), got \(syncStatus)", codingPath: codingPath)
        }
    }

    private static func validateVocabularyEntryRowState(
        syncStatus: Int,
        actionType: String,
        owner: String,
        codingPath: [CodingKey]
    ) throws {
        guard [0, 1, 2].contains(syncStatus) else {
            throw dataCorrupted("\(owner).syncStatus must be valid VocabularyEntry.syncStatus (0=pending, 1=synced, 2=failed), got \(syncStatus)", codingPath: codingPath)
        }
        guard ["add", "delete", "edit"].contains(actionType) else {
            throw dataCorrupted("\(owner).actionType must be add/delete/edit, got \(actionType)", codingPath: codingPath)
        }
    }

    private static func validateUniqueValues(
        _ values: [String],
        owner: String,
        codingPath: [CodingKey]
    ) throws {
        guard Set(values).count == values.count else {
            throw dataCorrupted("\(owner) must not contain duplicate values", codingPath: codingPath)
        }
    }

    private static func validateRuntimePodcastAssetReferences(
        _ seeds: [String: UIWorldRuntimePodcastSeed],
        assets: UIWorldAssetManifest,
        codingPath: [CodingKey]
    ) throws {
        for (fixtureID, seed) in seeds {
            try requireAssetRef(
                seed.audioAssetRef,
                prefix: "audio.",
                assets: assets,
                owner: "runtimePodcast.\(fixtureID).audioAssetRef",
                codingPath: codingPath
            )
            try requireAssetRef(
                seed.subtitleAssetRef,
                prefix: "subtitles.",
                assets: assets,
                owner: "runtimePodcast.\(fixtureID).subtitleAssetRef",
                codingPath: codingPath
            )
            for episode in seed.episodes {
                guard let download = episode.download else { continue }
                let audioOwner = "runtimePodcast.\(fixtureID).episodes.\(episode.remoteId).download.audioAssetRef"
                try requireAssetRef(
                    download.audioAssetRef,
                    prefix: "audio.",
                    assets: assets,
                    owner: audioOwner,
                    codingPath: codingPath
                )
                guard let audioAsset = assets.asset(for: download.audioAssetRef) else {
                    throw dataCorrupted("UI World \(audioOwner) references missing asset \(download.audioAssetRef)", codingPath: codingPath)
                }
                try validateDownloadLocalPath(
                    download.localAudioPath,
                    expectedInstallAs: audioAsset.installAs,
                    owner: "runtimePodcast.\(fixtureID).episodes.\(episode.remoteId).download.localAudioPath",
                    codingPath: codingPath
                )
                if let subtitleAssetRef = download.subtitleAssetRef {
                    let subtitleOwner = "runtimePodcast.\(fixtureID).episodes.\(episode.remoteId).download.subtitleAssetRef"
                    try requireAssetRef(
                        subtitleAssetRef,
                        prefix: "subtitles.",
                        assets: assets,
                        owner: subtitleOwner,
                        codingPath: codingPath
                    )
                    guard let subtitleAsset = assets.asset(for: subtitleAssetRef) else {
                        throw dataCorrupted("UI World \(subtitleOwner) references missing asset \(subtitleAssetRef)", codingPath: codingPath)
                    }
                    try validateDownloadLocalPath(
                        download.localSubtitlePath,
                        expectedInstallAs: subtitleAsset.installAs,
                        owner: "runtimePodcast.\(fixtureID).episodes.\(episode.remoteId).download.localSubtitlePath",
                        codingPath: codingPath
                    )
                } else {
                    try validateDownloadLocalPath(
                        download.localSubtitlePath,
                        expectedInstallAs: nil,
                        owner: "runtimePodcast.\(fixtureID).episodes.\(episode.remoteId).download.localSubtitlePath",
                        codingPath: codingPath
                    )
                }
            }
        }
    }

    private static func validateReaderAssetReferences(
        _ seeds: [String: UIWorldReaderSeed],
        assets: UIWorldAssetManifest,
        codingPath: [CodingKey]
    ) throws {
        for (fixtureID, seed) in seeds {
            try requireAssetRef(
                seed.textAssetRef,
                prefix: "text.",
                assets: assets,
                owner: "reader.\(fixtureID).textAssetRef",
                codingPath: codingPath
            )
            try requireAssetRef(
                seed.bookAssetRef,
                prefix: "books.",
                assets: assets,
                owner: "reader.\(fixtureID).bookAssetRef",
                codingPath: codingPath
            )
        }
    }

    private static func validateBookshelfAssetReferences(
        _ seeds: [String: BookshelfFixtureSeed],
        assets: UIWorldAssetManifest,
        codingPath: [CodingKey]
    ) throws {
        for (fixtureID, seed) in seeds {
            for book in seed.books {
                guard let bookAssetRef = book.bookAssetRef else { continue }
                try requireAssetRef(
                    bookAssetRef,
                    prefix: "books.",
                    assets: assets,
                    owner: "bookshelf.\(fixtureID).\(book.title).bookAssetRef",
                    codingPath: codingPath
                )
            }
        }
    }

    private static func requireAssetRef(
        _ ref: String,
        prefix: String,
        assets: UIWorldAssetManifest,
        owner: String,
        codingPath: [CodingKey]
    ) throws {
        guard ref.hasPrefix(prefix) else {
            throw dataCorrupted("UI World \(owner) must reference a \(prefix) asset, got \(ref)", codingPath: codingPath)
        }
        guard assets.asset(for: ref) != nil else {
            throw dataCorrupted("UI World \(owner) references missing asset \(ref)", codingPath: codingPath)
        }
    }

    private static func validateDownloadLocalPath(
        _ path: String?,
        expectedInstallAs: String?,
        owner: String,
        codingPath: [CodingKey]
    ) throws {
        guard let expectedInstallAs else {
            if path != nil {
                throw dataCorrupted("UI World \(owner) must be null when subtitleAssetRef is null", codingPath: codingPath)
            }
            return
        }
        guard let path, !path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw dataCorrupted("UI World \(owner) must explicitly declare a non-empty local path", codingPath: codingPath)
        }
        guard !path.hasPrefix("/") else {
            throw dataCorrupted("UI World \(owner) must be relative to Documents, got \(path)", codingPath: codingPath)
        }
        let components = path.split(separator: "/").map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw dataCorrupted("UI World \(owner) contains an unsafe path component: \(path)", codingPath: codingPath)
        }
        guard path == expectedInstallAs else {
            throw dataCorrupted(
                "UI World \(owner) must match asset installAs \(expectedInstallAs), got \(path)",
                codingPath: codingPath
            )
        }
    }

    private static func dataCorrupted(_ debugDescription: String, codingPath: [CodingKey]) -> DecodingError {
        DecodingError.dataCorrupted(
            .init(
                codingPath: codingPath,
                debugDescription: debugDescription
            )
        )
    }
}

// MARK: - Optional scenario context

/// Cross-domain inputs shared by scenarios that must render a coherent state:
/// a frozen review clock, a reader passage and a Word Detail seed.
