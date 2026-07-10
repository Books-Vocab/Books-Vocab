import Foundation
import CryptoKit

private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"
// base64(raw DEFLATE(JSON)) — preferred injection key. Plaintext base64 of a
// multi-MB UI World overflows the ~1MB posix_spawn env block and the app then
// silently sees *no* dataset; compressing keeps large worlds under the limit.
// Apple `.zlib` decompression expects a raw DEFLATE stream (no zlib/gzip
// container) — producers must use e.g. Python `zlib.compressobj(wbits=-15)`.
private let fixtureDatasetDeflateEnvKey = "KG_FIXTURE_DATASET_DEFLATE_B64"

private struct AnyCodingKey: CodingKey {
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
    /// Marketing screenshot capture domain (Phase 1 data plane). Optional by
    /// design: it is *not* a required v2 domain — even the checked-in fixtures
    /// carry a null `reviewClock`, and it only turns fully frozen in a marketing
    /// emit. Phase 2 catalog scenes read it to drive the website shots.
    let marketingCapture: MarketingCaptureSeed?

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
        case marketingCapture
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
        marketingCapture: MarketingCaptureSeed? = nil
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
        self.marketingCapture = marketingCapture
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
        marketingCapture = try container.decodeIfPresent(MarketingCaptureSeed.self, forKey: .marketingCapture)

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

// MARK: - Marketing capture (Phase 1 data plane → Phase 2 catalog scenes)

/// The `marketingCapture` top-level domain. Phase 1 emits this from the real
/// marketing-account SoT so the four website screenshots render off real data:
/// a frozen anchor-day clock (`reviewClock`), the reader passage projection
/// (`readerPassage`), and the Word Detail seed (`wordDetail`).
struct MarketingCaptureSeed: Codable, Equatable {
    /// Anchor-day freeze clock. Null in QA / checked-in baseline worlds; a full
    /// clock only in a frozen marketing emit. `frozenEpoch` (= preferences
    /// `review_settings_progress_paused_at`) is the load-bearing field.
    let reviewClock: MarketingReviewClockSeed?
    /// Reader marketing passage (real book prose + highlight words).
    let readerPassage: MarketingReaderPassageSeed?
    /// Word Detail marketing seed — `entries[0]` is the focused hero card, the
    /// rest are its graph-link targets. Reuses the vocabulary seed shape.
    let wordDetail: UIWorldVocabularySeed?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case reviewClock
        case readerPassage
        case wordDetail
    }

    init(
        reviewClock: MarketingReviewClockSeed? = nil,
        readerPassage: MarketingReaderPassageSeed? = nil,
        wordDetail: UIWorldVocabularySeed? = nil
    ) {
        self.reviewClock = reviewClock
        self.readerPassage = readerPassage
        self.wordDetail = wordDetail
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World marketingCapture contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        reviewClock = try container.decodeIfPresent(MarketingReviewClockSeed.self, forKey: .reviewClock)
        readerPassage = try container.decodeIfPresent(MarketingReaderPassageSeed.self, forKey: .readerPassage)
        wordDetail = try container.decodeIfPresent(UIWorldVocabularySeed.self, forKey: .wordDetail)
    }
}

/// Frozen review clock. All fields optional per the Phase 1 contract; a frozen
/// emit populates every field, and `frozenEpoch` == preferences
/// `review_settings_progress_paused_at`.
struct MarketingReviewClockSeed: Codable, Equatable {
    let frozenNow: String?
    let frozenEpoch: Int?
    let anchorDay: String?
    let source: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case frozenNow
        case frozenEpoch
        case anchorDay
        case source
    }

    init(frozenNow: String? = nil, frozenEpoch: Int? = nil, anchorDay: String? = nil, source: String? = nil) {
        self.frozenNow = frozenNow
        self.frozenEpoch = frozenEpoch
        self.anchorDay = anchorDay
        self.source = source
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World marketingCapture.reviewClock contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        frozenNow = try container.decodeIfPresent(String.self, forKey: .frozenNow)
        frozenEpoch = try container.decodeIfPresent(Int.self, forKey: .frozenEpoch)
        anchorDay = try container.decodeIfPresent(String.self, forKey: .anchorDay)
        source = try container.decodeIfPresent(String.self, forKey: .source)
    }
}

/// Reader marketing passage. `activeWord` is the just-tapped word tied to the
/// translation overlay; it is guaranteed to appear as a token in `paragraphs`.
/// `activeWords == [activeWord]`.
struct MarketingReaderPassageSeed: Codable, Equatable {
    let bookTitle: String
    let activeWord: String
    let activePartOfSpeech: String
    let activeTranslation: String
    let activeExplanation: String
    let activeContext: String
    let paragraphs: [String]
    let vocabWords: [String]
    let activeWords: [String]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case bookTitle
        case activeWord
        case activePartOfSpeech
        case activeTranslation
        case activeExplanation
        case activeContext
        case paragraphs
        case vocabWords
        case activeWords
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World marketingCapture.readerPassage contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World marketingCapture.readerPassage must explicitly declare \(key.rawValue)"
                )
            )
        }
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        activeWord = try container.decode(String.self, forKey: .activeWord)
        activePartOfSpeech = try container.decode(String.self, forKey: .activePartOfSpeech)
        activeTranslation = try container.decode(String.self, forKey: .activeTranslation)
        activeExplanation = try container.decode(String.self, forKey: .activeExplanation)
        activeContext = try container.decode(String.self, forKey: .activeContext)
        paragraphs = try container.decode([String].self, forKey: .paragraphs)
        vocabWords = try container.decode([String].self, forKey: .vocabWords)
        activeWords = try container.decode([String].self, forKey: .activeWords)
    }
}

enum UIWorldPreferenceValue: Codable, Equatable {
    case string(String)
    case double(Double)
    case bool(Bool)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "UI World preference values must be string, number, or bool"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        }
    }
}

struct UIWorldPreferencesSeed: Codable, Equatable {
    static let userDefaultsKeys: Set<String> = [
        "activeNotebookId",
        "active_notebook_updated_at",
        "app_appearance_selection",
        "app_language_selection",
        "auto_sync_enabled",
        "hasSeenWelcome",
        "kg_last_incremental_sync",
        "kg_review_payload_version",
        "podcast.autoPauseOnLookup",
        "podcast.subtitleSize",
        "podcast.wordFollowEnabled",
        "reader_settings_font",
        "reader_settings_fontSize",
        "reader_settings_lineHeight",
        "reader_settings_scrollMode",
        "reader_settings_showHitTestingDebug",
        "reader_settings_underlineOpacity",
        "review_settings_autoplay_sound_enabled",
        "review_settings_autoplay_speed",
        "review_settings_custom_params",
        "review_settings_mode",
        "review_settings_mode_updated_at",
        "review_settings_progress_paused",
        "review_settings_progress_paused_at",
        "review_settings_progress_updated_at",
        "translation_source_lang",
        "translation_source_lang_updated_at",
        "translation_target_lang",
        "translation_target_lang_updated_at",
        "vocab_highlight_colorPreset",
        "vocab_highlight_opacity",
    ]
    static let ubiquitousKeyValueStoreKeys: Set<String> = [
        "activeNotebookId",
        "active_notebook_updated_at",
        "app_appearance_selection",
        "app_language_selection",
        "reader_settings_font",
        "reader_settings_fontSize",
        "reader_settings_lineHeight",
        "reader_settings_scrollMode",
        "reader_settings_underlineOpacity",
        "review_settings_custom_params",
        "review_settings_mode",
        "review_settings_mode_updated_at",
        "review_settings_progress_paused",
        "review_settings_progress_paused_at",
        "review_settings_progress_updated_at",
        "translation_source_lang",
        "translation_source_lang_updated_at",
        "translation_target_lang",
        "translation_target_lang_updated_at",
        "vocab_highlight_colorPreset",
        "vocab_highlight_opacity",
    ]

    let userDefaults: [String: UIWorldPreferenceValue]
    let ubiquitousKeyValueStore: [String: UIWorldPreferenceValue]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case userDefaults
        case ubiquitousKeyValueStore
    }

    static let empty = UIWorldPreferencesSeed(userDefaults: [:], ubiquitousKeyValueStore: [:])

    init(
        userDefaults: [String: UIWorldPreferenceValue],
        ubiquitousKeyValueStore: [String: UIWorldPreferenceValue]
    ) {
        self.userDefaults = userDefaults
        self.ubiquitousKeyValueStore = ubiquitousKeyValueStore
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World preferences seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World preferences seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        userDefaults = try container.decode([String: UIWorldPreferenceValue].self, forKey: .userDefaults)
        ubiquitousKeyValueStore = try container.decode([String: UIWorldPreferenceValue].self, forKey: .ubiquitousKeyValueStore)
    }

    var isEmpty: Bool {
        userDefaults.isEmpty && ubiquitousKeyValueStore.isEmpty
    }

    func apply(
        to defaults: UserDefaults = .standard,
        cloud: CloudKeyValueStore = CloudPreferencesSync.shared
    ) {
        for (key, value) in userDefaults {
            precondition(!key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, "UI World preferences contains an empty UserDefaults key")
            switch value {
            case .string(let string):
                defaults.set(string, forKey: key)
            case .double(let double):
                defaults.set(double, forKey: key)
            case .bool(let bool):
                defaults.set(bool, forKey: key)
            }
        }
        for (key, value) in ubiquitousKeyValueStore {
            precondition(!key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, "UI World preferences contains an empty iCloud KVS key")
            switch value {
            case .string(let string):
                cloud.set(string, forKey: key)
            case .double(let double):
                cloud.set(double, forKey: key)
            case .bool(let bool):
                cloud.set(bool ? 1.0 : 0.0, forKey: key)
            }
        }
    }
}

struct UIWorldAsset: Codable, Equatable {
    let sourcePath: String
    let sha256: String
    let byteSize: Int
    let installAs: String
    let contentType: String

    enum CodingKeys: String, CodingKey, CaseIterable {
        case sourcePath
        case sha256
        case byteSize
        case installAs
        case contentType
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World asset contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World asset must explicitly declare \(key.rawValue)"
                )
            )
        }
        sourcePath = try container.decode(String.self, forKey: .sourcePath)
        sha256 = try container.decode(String.self, forKey: .sha256)
        byteSize = try container.decode(Int.self, forKey: .byteSize)
        installAs = try container.decode(String.self, forKey: .installAs)
        contentType = try container.decode(String.self, forKey: .contentType)
        try Self.validateSourcePath(sourcePath, codingPath: container.codingPath)
        try Self.validateSHA256(sha256, codingPath: container.codingPath)
        try Self.validateByteSize(byteSize, codingPath: container.codingPath)
        try Self.validateInstallAs(installAs, codingPath: container.codingPath)
    }

    private static func validateSourcePath(_ sourcePath: String, codingPath: [CodingKey]) throws {
        guard !sourcePath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset sourcePath must be a non-empty path"
                )
            )
        }
    }

    private static func validateSHA256(_ sha256: String, codingPath: [CodingKey]) throws {
        let pattern = #"^[0-9a-f]{64}$"#
        guard sha256.range(of: pattern, options: .regularExpression) != nil else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset sha256 must be lowercase 64 hex characters"
                )
            )
        }
    }

    private static func validateByteSize(_ byteSize: Int, codingPath: [CodingKey]) throws {
        guard byteSize > 0 else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset byteSize must be a positive integer"
                )
            )
        }
    }

    private static func validateInstallAs(_ installAs: String, codingPath: [CodingKey]) throws {
        let trimmed = installAs.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset installAs must be a non-empty relative path"
                )
            )
        }
        guard !trimmed.hasPrefix("/") else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset installAs must be relative: \(trimmed)"
                )
            )
        }
        let components = trimmed.split(separator: "/").map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "UI World asset installAs contains an unsafe path component: \(trimmed)"
                )
            )
        }
    }
}

struct UIWorldAssetManifest: Codable, Equatable {
    private static let contentTypesByBucket: [String: Set<String>] = [
        "books": ["application/epub+zip", "application/pdf", "text/markdown; charset=utf-8", "text/plain; charset=utf-8"],
        "audio": ["audio/mp4", "audio/mpeg"],
        "subtitles": ["application/x-subrip; charset=utf-8", "text/vtt; charset=utf-8"],
        "text": ["text/markdown; charset=utf-8", "text/plain; charset=utf-8"],
        "images": ["image/png", "image/jpeg"],
    ]
    private static let contentTypesByExtension: [String: String] = [
        "epub": "application/epub+zip",
        "pdf": "application/pdf",
        "md": "text/markdown; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "srt": "application/x-subrip; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    ]

    let books: [String: UIWorldAsset]
    let audio: [String: UIWorldAsset]
    let subtitles: [String: UIWorldAsset]
    let text: [String: UIWorldAsset]
    let images: [String: UIWorldAsset]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case books
        case audio
        case subtitles
        case text
        case images
    }

    init(
        books: [String: UIWorldAsset],
        audio: [String: UIWorldAsset],
        subtitles: [String: UIWorldAsset],
        text: [String: UIWorldAsset],
        images: [String: UIWorldAsset]
    ) {
        self.books = books
        self.audio = audio
        self.subtitles = subtitles
        self.text = text
        self.images = images
    }

    static let empty = UIWorldAssetManifest(
        books: [:],
        audio: [:],
        subtitles: [:],
        text: [:],
        images: [:]
    )

    var isEmpty: Bool {
        books.isEmpty && audio.isEmpty && subtitles.isEmpty && text.isEmpty && images.isEmpty
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World asset manifest contains unknown buckets \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World asset manifest must explicitly declare \(key.rawValue)"
                )
            )
        }
        books = try container.decode([String: UIWorldAsset].self, forKey: .books)
        audio = try container.decode([String: UIWorldAsset].self, forKey: .audio)
        subtitles = try container.decode([String: UIWorldAsset].self, forKey: .subtitles)
        text = try container.decode([String: UIWorldAsset].self, forKey: .text)
        images = try container.decode([String: UIWorldAsset].self, forKey: .images)
        try Self.validateUniqueInstallPaths(
            buckets: [
                "books": books,
                "audio": audio,
                "subtitles": subtitles,
                "text": text,
                "images": images,
            ],
            codingPath: container.codingPath
        )
        try Self.validateContentTypes(
            buckets: [
                "books": books,
                "audio": audio,
                "subtitles": subtitles,
                "text": text,
                "images": images,
            ],
            codingPath: container.codingPath
        )
    }

    var refs: [String] {
        [
            books.keys.map { "books.\($0)" },
            audio.keys.map { "audio.\($0)" },
            subtitles.keys.map { "subtitles.\($0)" },
            text.keys.map { "text.\($0)" },
            images.keys.map { "images.\($0)" },
        ].flatMap { $0 }.sorted()
    }

    func asset(for ref: String) -> UIWorldAsset? {
        let parts = ref.split(separator: ".", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return nil }
        switch parts[0] {
        case "books": return books[parts[1]]
        case "audio": return audio[parts[1]]
        case "subtitles": return subtitles[parts[1]]
        case "text": return text[parts[1]]
        case "images": return images[parts[1]]
        default: return nil
        }
    }

    private static func validateUniqueInstallPaths(
        buckets: [String: [String: UIWorldAsset]],
        codingPath: [CodingKey]
    ) throws {
        var seen: [String: String] = [:]
        for (bucket, assets) in buckets {
            for (assetID, asset) in assets {
                let installAs = asset.installAs.trimmingCharacters(in: .whitespacesAndNewlines)
                let ref = "\(bucket).\(assetID)"
                if let previous = seen[installAs] {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World assets \(previous) and \(ref) share installAs \(installAs)"
                        )
                    )
                }
                seen[installAs] = ref
            }
        }
    }

    private static func validateContentTypes(
        buckets: [String: [String: UIWorldAsset]],
        codingPath: [CodingKey]
    ) throws {
        for (bucket, assets) in buckets {
            for (assetID, asset) in assets {
                let ref = "\(bucket).\(assetID)"
                guard contentTypesByBucket[bucket]?.contains(asset.contentType) == true else {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World asset \(ref) contentType \(asset.contentType) is invalid for \(bucket)"
                        )
                    )
                }
                let installExtension = URL(fileURLWithPath: asset.installAs).pathExtension.lowercased()
                let sourceExtension = URL(fileURLWithPath: asset.sourcePath).pathExtension.lowercased()
                let ext = installExtension.isEmpty ? sourceExtension : installExtension
                if let expected = contentTypesByExtension[ext], asset.contentType != expected {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: codingPath,
                            debugDescription: "UI World asset \(ref) contentType \(asset.contentType) must match .\(ext) as \(expected)"
                        )
                    )
                }
            }
        }
    }
}

enum UIWorldAuthFixtureID: String, CaseIterable {
    case guest
    case guestAuthenticating
    case guestError
    case signedIn
    case settingsSignedIn
    case longIdentity
}

struct UIWorldAuthSeed: Codable, Equatable {
    enum KeychainTokenState: String, Codable {
        case available
        case readFailed
        case absent
    }

    let isLoggedIn: Bool
    let userId: String?
    let token: String?
    let keychainTokenState: KeychainTokenState
    let displayName: String?
    let email: String?
    let authError: String?
    let isAuthenticating: Bool
    let provider: String?
    let providerUserId: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case isLoggedIn
        case userId
        case token
        case keychainTokenState
        case displayName
        case email
        case authError
        case isAuthenticating
        case provider
        case providerUserId
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World auth seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World auth seed must explicitly declare \(key.rawValue), even when null"
                )
            )
        }
        isLoggedIn = try container.decode(Bool.self, forKey: .isLoggedIn)
        userId = try container.decodeIfPresent(String.self, forKey: .userId)
        token = try container.decodeIfPresent(String.self, forKey: .token)
        keychainTokenState = try container.decode(KeychainTokenState.self, forKey: .keychainTokenState)
        displayName = try container.decodeIfPresent(String.self, forKey: .displayName)
        email = try container.decodeIfPresent(String.self, forKey: .email)
        authError = try container.decodeIfPresent(String.self, forKey: .authError)
        isAuthenticating = try container.decode(Bool.self, forKey: .isAuthenticating)
        provider = try container.decodeIfPresent(String.self, forKey: .provider)
        providerUserId = try container.decodeIfPresent(String.self, forKey: .providerUserId)
    }
}

enum UIWorldSyncPresenterFixtureID: String, CaseIterable {
    case ready
    case running
    case completed
    case partialFailure
    case fullFailure
}

struct UIWorldSyncPresenterSeed: Codable, Equatable {
    struct Step: Codable, Equatable {
        let id: String
        let label: String
        let status: String
        let current: Int
        let total: Int
        let detail: String

        enum CodingKeys: String, CodingKey, CaseIterable {
            case id
            case label
            case status
            case current
            case total
            case detail
        }

        init(from decoder: Decoder) throws {
            try UIWorldSyncPresenterSeed.rejectUnknownKeys(
                decoder: decoder,
                keys: CodingKeys.allCases,
                context: "UI World syncPresenter step"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            for key in CodingKeys.allCases where !container.contains(key) {
                throw DecodingError.keyNotFound(
                    key,
                    DecodingError.Context(
                        codingPath: container.codingPath,
                        debugDescription: "UI World syncPresenter step must explicitly declare \(key.rawValue)"
                    )
                )
            }
            id = try container.decode(String.self, forKey: .id)
            label = try container.decode(String.self, forKey: .label)
            status = try container.decode(String.self, forKey: .status)
            current = try container.decode(Int.self, forKey: .current)
            total = try container.decode(Int.self, forKey: .total)
            detail = try container.decode(String.self, forKey: .detail)
        }
    }

    struct PendingRow: Codable, Equatable {
        let id: String
        let word: String
        let partOfSpeech: String?
        let translation: String
        let wordTone: String
        let isStrikethrough: Bool
        let actionSystemImage: String
        let actionTone: String
        let actionAccessibilityLabel: String

        enum CodingKeys: String, CodingKey, CaseIterable {
            case id
            case word
            case partOfSpeech
            case translation
            case wordTone
            case isStrikethrough
            case actionSystemImage
            case actionTone
            case actionAccessibilityLabel
        }

        init(from decoder: Decoder) throws {
            try UIWorldSyncPresenterSeed.rejectUnknownKeys(
                decoder: decoder,
                keys: CodingKeys.allCases,
                context: "UI World syncPresenter pending row"
            )
            let container = try decoder.container(keyedBy: CodingKeys.self)
            for key in CodingKeys.allCases where !container.contains(key) {
                throw DecodingError.keyNotFound(
                    key,
                    DecodingError.Context(
                        codingPath: container.codingPath,
                        debugDescription: "UI World syncPresenter pending row must explicitly declare \(key.rawValue)"
                    )
                )
            }
            id = try container.decode(String.self, forKey: .id)
            word = try container.decode(String.self, forKey: .word)
            partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
            translation = try container.decode(String.self, forKey: .translation)
            wordTone = try container.decode(String.self, forKey: .wordTone)
            isStrikethrough = try container.decode(Bool.self, forKey: .isStrikethrough)
            actionSystemImage = try container.decode(String.self, forKey: .actionSystemImage)
            actionTone = try container.decode(String.self, forKey: .actionTone)
            actionAccessibilityLabel = try container.decode(String.self, forKey: .actionAccessibilityLabel)
        }
    }

    let isLoggedIn: Bool
    let isConnected: Bool
    let phase: String
    let failureKind: String?
    let pendingCount: Int
    let addCount: Int
    let deleteCount: Int
    let steps: [Step]
    let summaryText: String
    let pendingRows: [PendingRow]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case isLoggedIn
        case isConnected
        case phase
        case failureKind
        case pendingCount
        case addCount
        case deleteCount
        case steps
        case summaryText
        case pendingRows
    }

    init(from decoder: Decoder) throws {
        try Self.rejectUnknownKeys(
            decoder: decoder,
            keys: CodingKeys.allCases,
            context: "UI World syncPresenter seed"
        )
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try Self.requireAllKeys(in: container, context: "UI World syncPresenter seed")
        isLoggedIn = try container.decode(Bool.self, forKey: .isLoggedIn)
        isConnected = try container.decode(Bool.self, forKey: .isConnected)
        phase = try container.decode(String.self, forKey: .phase)
        failureKind = try container.decodeIfPresent(String.self, forKey: .failureKind)
        pendingCount = try container.decode(Int.self, forKey: .pendingCount)
        addCount = try container.decode(Int.self, forKey: .addCount)
        deleteCount = try container.decode(Int.self, forKey: .deleteCount)
        steps = try container.decode([Step].self, forKey: .steps)
        summaryText = try container.decode(String.self, forKey: .summaryText)
        pendingRows = try container.decode([PendingRow].self, forKey: .pendingRows)
    }

    fileprivate static func rejectUnknownKeys<K: CodingKey & RawRepresentable>(
        decoder: Decoder,
        keys: [K],
        context: String
    ) throws where K.RawValue == String {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
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

    private static func requireAllKeys<C: KeyedDecodingContainerProtocol>(
        in container: C,
        context: String
    ) throws where C.Key: CaseIterable & RawRepresentable, C.Key.RawValue == String {
        for key in C.Key.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "\(context) must explicitly declare \(key.rawValue)"
                )
            )
        }
    }
}

enum UIWorldEntitlementsFixtureID: String, CaseIterable {
    case adminGranted
    case cancelledButActive
    case free
    case pro
}

struct UIWorldEntitlementsSeed: Codable, Equatable {
    let pro: KGSubscriptionStatus

    enum CodingKeys: String, CodingKey, CaseIterable {
        case pro
    }

    private enum ProCodingKeys: String, CodingKey, CaseIterable {
        case is_active
        case product_id
        case plan_name
        case price_display
        case status
        case is_trial
        case trial_days
        case will_renew
        case expires_at
        case source
        case last_synced_at
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World entitlements seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World entitlements seed must explicitly declare \(key.rawValue)"
                )
            )
        }

        let rawProContainer = try container.nestedContainer(keyedBy: AnyCodingKey.self, forKey: .pro)
        let unknownProKeys = Set(rawProContainer.allKeys.map(\.stringValue))
            .subtracting(ProCodingKeys.allCases.map(\.rawValue))
        guard unknownProKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: rawProContainer.codingPath,
                    debugDescription: "UI World entitlements pro status contains unknown keys \(unknownProKeys.sorted())"
                )
            )
        }

        let proContainer = try container.nestedContainer(keyedBy: ProCodingKeys.self, forKey: .pro)
        for key in ProCodingKeys.allCases where !proContainer.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: proContainer.codingPath,
                    debugDescription: "UI World entitlements pro status must explicitly declare \(key.rawValue), even when null"
                )
            )
        }

        pro = try container.decode(KGSubscriptionStatus.self, forKey: .pro)
    }
}

enum UIWorldRuntimePodcastFixtureID: String, CaseIterable {
    case playablePreview
    case tieredCatalog
}

struct UIWorldRuntimePodcastEpisodeSeed: Codable, Equatable {
    struct Download: Codable, Equatable {
        let audioAssetRef: String
        let subtitleAssetRef: String?
        let localAudioPath: String
        let localSubtitlePath: String?

        enum CodingKeys: String, CodingKey, CaseIterable {
            case audioAssetRef
            case subtitleAssetRef
            case localAudioPath
            case localSubtitlePath
        }

        init(
            audioAssetRef: String,
            subtitleAssetRef: String?,
            localAudioPath: String,
            localSubtitlePath: String?
        ) {
            self.audioAssetRef = audioAssetRef
            self.subtitleAssetRef = subtitleAssetRef
            self.localAudioPath = localAudioPath
            self.localSubtitlePath = localSubtitlePath
        }

        init(from decoder: Decoder) throws {
            let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
            let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
                .subtracting(CodingKeys.allCases.map(\.rawValue))
            guard unknownKeys.isEmpty else {
                throw DecodingError.dataCorrupted(
                    .init(
                        codingPath: decoder.codingPath,
                        debugDescription: "UI World runtime podcast download contains unknown keys \(unknownKeys.sorted())"
                    )
                )
            }

            let container = try decoder.container(keyedBy: CodingKeys.self)
            for key in CodingKeys.allCases where !container.contains(key) {
                throw DecodingError.keyNotFound(
                    key,
                    .init(
                        codingPath: decoder.codingPath,
                        debugDescription: "UI World runtime podcast download must explicitly declare \(key.rawValue)"
                    )
                )
            }

            audioAssetRef = try container.decode(String.self, forKey: .audioAssetRef)
            subtitleAssetRef = try container.decodeIfPresent(String.self, forKey: .subtitleAssetRef)
            localAudioPath = try container.decode(String.self, forKey: .localAudioPath)
            localSubtitlePath = try container.decodeIfPresent(String.self, forKey: .localSubtitlePath)
        }
    }

    let remoteId: String
    let episodeNumber: Int
    let title: String
    let durationSec: Double
    let audioAvailable: Bool
    let previewAvailable: Bool
    let previewDurationSec: Double
    let subtitleAvailable: Bool
    let download: Download?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case remoteId
        case episodeNumber
        case title
        case durationSec
        case audioAvailable
        case previewAvailable
        case previewDurationSec
        case subtitleAvailable
        case download
    }

    init(
        remoteId: String,
        episodeNumber: Int,
        title: String,
        durationSec: Double,
        audioAvailable: Bool,
        previewAvailable: Bool,
        previewDurationSec: Double,
        subtitleAvailable: Bool,
        download: Download?
    ) {
        self.remoteId = remoteId
        self.episodeNumber = episodeNumber
        self.title = title
        self.durationSec = durationSec
        self.audioAvailable = audioAvailable
        self.previewAvailable = previewAvailable
        self.previewDurationSec = previewDurationSec
        self.subtitleAvailable = subtitleAvailable
        self.download = download
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast episode contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast episode must explicitly declare \(key.rawValue)"
                )
            )
        }

        remoteId = try container.decode(String.self, forKey: .remoteId)
        episodeNumber = try container.decode(Int.self, forKey: .episodeNumber)
        title = try container.decode(String.self, forKey: .title)
        durationSec = try container.decode(Double.self, forKey: .durationSec)
        audioAvailable = try container.decode(Bool.self, forKey: .audioAvailable)
        previewAvailable = try container.decode(Bool.self, forKey: .previewAvailable)
        previewDurationSec = try container.decode(Double.self, forKey: .previewDurationSec)
        subtitleAvailable = try container.decode(Bool.self, forKey: .subtitleAvailable)
        download = try container.decodeIfPresent(Download.self, forKey: .download)
    }
}

struct UIWorldRuntimePodcastSeed: Codable, Equatable {
    let audioAssetRef: String
    let subtitleAssetRef: String
    let seriesRemoteId: String
    let seriesTitle: String
    let hostNames: [String]
    let preferredNotebookId: String?
    let color: String?
    let coverPattern: String?
    let sortOrder: Int
    let durationSec: Double
    let episodes: [UIWorldRuntimePodcastEpisodeSeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case audioAssetRef
        case subtitleAssetRef
        case seriesRemoteId
        case seriesTitle
        case hostNames
        case preferredNotebookId
        case color
        case coverPattern
        case sortOrder
        case durationSec
        case episodes
    }

    init(
        audioAssetRef: String,
        subtitleAssetRef: String,
        seriesRemoteId: String,
        seriesTitle: String,
        hostNames: [String],
        preferredNotebookId: String?,
        color: String?,
        coverPattern: String?,
        sortOrder: Int,
        durationSec: Double,
        episodes: [UIWorldRuntimePodcastEpisodeSeed]
    ) {
        self.audioAssetRef = audioAssetRef
        self.subtitleAssetRef = subtitleAssetRef
        self.seriesRemoteId = seriesRemoteId
        self.seriesTitle = seriesTitle
        self.hostNames = hostNames
        self.preferredNotebookId = preferredNotebookId
        self.color = color
        self.coverPattern = coverPattern
        self.sortOrder = sortOrder
        self.durationSec = durationSec
        self.episodes = episodes
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast series contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World runtime podcast series must explicitly declare \(key.rawValue)"
                )
            )
        }

        audioAssetRef = try container.decode(String.self, forKey: .audioAssetRef)
        subtitleAssetRef = try container.decode(String.self, forKey: .subtitleAssetRef)
        seriesRemoteId = try container.decode(String.self, forKey: .seriesRemoteId)
        seriesTitle = try container.decode(String.self, forKey: .seriesTitle)
        hostNames = try container.decode([String].self, forKey: .hostNames)
        preferredNotebookId = try container.decodeIfPresent(String.self, forKey: .preferredNotebookId)
        color = try container.decodeIfPresent(String.self, forKey: .color)
        coverPattern = try container.decodeIfPresent(String.self, forKey: .coverPattern)
        sortOrder = try container.decode(Int.self, forKey: .sortOrder)
        durationSec = try container.decode(Double.self, forKey: .durationSec)
        episodes = try container.decode([UIWorldRuntimePodcastEpisodeSeed].self, forKey: .episodes)
    }
}

enum UIWorldReaderFixtureID: String, CaseIterable {
    case realBookLibrary
}

struct UIWorldReaderSeed: Codable, Equatable {
    let textAssetRef: String
    let bookAssetRef: String
    let title: String
    let author: String
    let bookFileName: String
    let notebookRemoteId: String
    let notebookName: String
    let notebookSyncStatus: Int
    let entry: UIWorldVocabularyEntrySeed

    enum CodingKeys: String, CodingKey, CaseIterable {
        case textAssetRef
        case bookAssetRef
        case title
        case author
        case bookFileName
        case notebookRemoteId
        case notebookName
        case notebookSyncStatus
        case entry
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World reader seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World reader seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        textAssetRef = try container.decode(String.self, forKey: .textAssetRef)
        bookAssetRef = try container.decode(String.self, forKey: .bookAssetRef)
        title = try container.decode(String.self, forKey: .title)
        author = try container.decode(String.self, forKey: .author)
        bookFileName = try container.decode(String.self, forKey: .bookFileName)
        notebookRemoteId = try container.decode(String.self, forKey: .notebookRemoteId)
        notebookName = try container.decode(String.self, forKey: .notebookName)
        notebookSyncStatus = try container.decode(Int.self, forKey: .notebookSyncStatus)
        entry = try container.decode(UIWorldVocabularyEntrySeed.self, forKey: .entry)
    }
}

enum UIWorldVocabularyFixtureID: String, CaseIterable {
    case archivedEmpty
    case archivedLong
    case archivedPopulated
    case archivedSingle
    case knowledgeGraphEmpty
    case knowledgeGraphPopulated
    case kgVocabRow
    case reviewCalendarDense
    case searchVocabNotebook
    case shellNavigation
    case statsEmpty
    case statsPopulated
    case syncEmpty
    case syncPendingMixed
    case syncPendingSingle
    case vocabLinkedCards
    case vocabListEmpty
    case vocabListLong
    case vocabListPopulated
    case vocabListSingle
    case vocabListSyncing
    case wordDetail
    case wordEdit
}

struct UIWorldVocabularySeed: Codable, Equatable {
    let notebookRemoteId: String
    let notebookName: String
    let notebookSyncStatus: Int
    let bookTitle: String
    let entries: [UIWorldVocabularyEntrySeed]
    let reviewHistory: [UIWorldReviewHistorySeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case notebookRemoteId
        case notebookName
        case notebookSyncStatus
        case bookTitle
        case entries
        case reviewHistory
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World vocabulary seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World vocabulary seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        notebookRemoteId = try container.decode(String.self, forKey: .notebookRemoteId)
        notebookName = try container.decode(String.self, forKey: .notebookName)
        notebookSyncStatus = try container.decode(Int.self, forKey: .notebookSyncStatus)
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        entries = try container.decode([UIWorldVocabularyEntrySeed].self, forKey: .entries)
        reviewHistory = try container.decode([UIWorldReviewHistorySeed].self, forKey: .reviewHistory)
    }
}

struct UIWorldReviewHistorySeed: Codable, Equatable {
    let word: String
    let feedback: Int
    let reviewedAt: Date

    enum CodingKeys: String, CodingKey, CaseIterable {
        case word
        case feedback
        case reviewedAt
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World review history contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World review history must explicitly declare \(key.rawValue)"
                )
            )
        }
        word = try container.decode(String.self, forKey: .word)
        feedback = try container.decode(Int.self, forKey: .feedback)
        reviewedAt = try container.decode(Date.self, forKey: .reviewedAt)
    }
}

enum UIWorldReviewDeckFixtureID: String, CaseIterable {
    case phaseLongContent
    case phaseMulti
    case phaseSingle
    case probe
    case notebookReviewDeck
}

struct UIWorldReviewDeckSeed: Codable, Equatable {
    let notebookRemoteId: String
    let notebookName: String
    let notebookSyncStatus: Int
    let entries: [UIWorldVocabularyEntrySeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case notebookRemoteId
        case notebookName
        case notebookSyncStatus
        case entries
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World review deck seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World review deck seed must explicitly declare \(key.rawValue)"
                )
            )
        }
        notebookRemoteId = try container.decode(String.self, forKey: .notebookRemoteId)
        notebookName = try container.decode(String.self, forKey: .notebookName)
        notebookSyncStatus = try container.decode(Int.self, forKey: .notebookSyncStatus)
        entries = try container.decode([UIWorldVocabularyEntrySeed].self, forKey: .entries)
    }
}

struct UIWorldVocabularyEntrySeed: Codable, Equatable {
    let word: String
    let translation: String
    let context: String
    let explanation: String?
    let partOfSpeech: String?
    let bookTitle: String
    let chapterTitle: String?
    let kgCardId: String?
    let difficultyTier: String?
    let reviewMode: VocabularyCardMode
    let reviewExamples: [String]
    let collocations: [String]?
    let rootForm: String?
    let inflections: [String]?
    let syncStatus: Int
    let actionType: String
    let isArchived: Bool
    let isExcludedFromReader: Bool
    let reviewIntervalHours: Double?
    let nextReviewAt: Date?
    let lastReviewedAt: Date?
    let reviewCount: Int?
    let reviewStreak: Int?
    let lastReviewFeedbackRaw: Int?
    let graphLinksByKind: [String: [KGCardLinkSummary]]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case word
        case translation
        case context
        case explanation
        case partOfSpeech
        case bookTitle
        case chapterTitle
        case kgCardId
        case difficultyTier
        case reviewMode
        case reviewExamples
        case collocations
        case rootForm
        case inflections
        case syncStatus
        case actionType
        case isArchived
        case isExcludedFromReader
        case reviewIntervalHours
        case nextReviewAt
        case lastReviewedAt
        case reviewCount
        case reviewStreak
        case lastReviewFeedbackRaw
        case graphLinksByKind
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World vocabulary entry contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "UI World vocabulary entry must explicitly declare \(key.rawValue)"
                )
            )
        }

        word = try container.decode(String.self, forKey: .word)
        translation = try container.decode(String.self, forKey: .translation)
        context = try container.decode(String.self, forKey: .context)
        explanation = try container.decodeIfPresent(String.self, forKey: .explanation)
        partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        chapterTitle = try container.decodeIfPresent(String.self, forKey: .chapterTitle)
        kgCardId = try container.decodeIfPresent(String.self, forKey: .kgCardId)
        difficultyTier = try container.decodeIfPresent(String.self, forKey: .difficultyTier)
        reviewMode = try container.decode(VocabularyCardMode.self, forKey: .reviewMode)
        reviewExamples = try container.decode([String].self, forKey: .reviewExamples)
        collocations = try container.decodeIfPresent([String].self, forKey: .collocations)
        rootForm = try container.decodeIfPresent(String.self, forKey: .rootForm)
        inflections = try container.decodeIfPresent([String].self, forKey: .inflections)
        syncStatus = try container.decode(Int.self, forKey: .syncStatus)
        actionType = try container.decode(String.self, forKey: .actionType)
        isArchived = try container.decode(Bool.self, forKey: .isArchived)
        isExcludedFromReader = try container.decode(Bool.self, forKey: .isExcludedFromReader)
        reviewIntervalHours = try container.decodeIfPresent(Double.self, forKey: .reviewIntervalHours)
        nextReviewAt = try container.decodeIfPresent(Date.self, forKey: .nextReviewAt)
        lastReviewedAt = try container.decodeIfPresent(Date.self, forKey: .lastReviewedAt)
        reviewCount = try container.decodeIfPresent(Int.self, forKey: .reviewCount)
        reviewStreak = try container.decodeIfPresent(Int.self, forKey: .reviewStreak)
        lastReviewFeedbackRaw = try container.decodeIfPresent(Int.self, forKey: .lastReviewFeedbackRaw)
        graphLinksByKind = try container.decode([String: [KGCardLinkSummary]].self, forKey: .graphLinksByKind)
    }
}

enum FixtureDatasetStore {
    @TaskLocal static var testingOverrideData: Data?

    static func withTestingData<T>(_ data: Data?, perform: () throws -> T) rethrows -> T {
        try $testingOverrideData.withValue(data) {
            try perform()
        }
    }

    static func withTestingData<T>(_ data: Data?, perform: () async throws -> T) async rethrows -> T {
        try await $testingOverrideData.withValue(data) {
            try await perform()
        }
    }

    static func settingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.settings[fixtureID.rawValue]
    }

    static func requireSettingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed {
        guard let seed = settingsSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "settings.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func authSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.auth[fixtureID.rawValue]
    }

    static func requireAuthSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed {
        guard let seed = authSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "auth.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func entitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.entitlements[fixtureID.rawValue]
    }

    static func requireEntitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed {
        guard let seed = entitlementsSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "entitlements.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func syncPresenterSeed(for fixtureID: UIWorldSyncPresenterFixtureID) -> UIWorldSyncPresenterSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.syncPresenter[fixtureID.rawValue]
    }

    static func requireSyncPresenterSeed(for fixtureID: UIWorldSyncPresenterFixtureID) -> UIWorldSyncPresenterSeed {
        guard let seed = syncPresenterSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "syncPresenter.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func bookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.bookshelf[fixtureID.rawValue]
    }

    static func requireBookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed {
        guard let seed = bookshelfSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "bookshelf.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func todayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.todayReview[fixtureID.rawValue]
    }

    static func requireTodayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed {
        guard let seed = todayReviewSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "todayReview.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func notebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.notebook[fixtureID.rawValue]
    }

    static func requireNotebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed {
        guard let seed = notebookSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "notebook.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func podcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.podcast[fixtureID.rawValue]
    }

    static func requirePodcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed {
        guard let seed = podcastSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "podcast.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func runtimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.runtimePodcast[fixtureID.rawValue]
    }

    static func requireRuntimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed {
        guard let seed = runtimePodcastSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "runtimePodcast.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func requireInstalledAssetURL(ref: String) throws -> URL {
        let asset = try requireAsset(ref: ref)
        let sourceURL = try validatedSourceURL(for: asset, ref: ref)
        let destination = try installURL(for: asset, ref: ref)
        let fm = FileManager.default
        try fm.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
        try fm.copyItem(at: sourceURL, to: destination)
        let installedSize = try byteSize(for: destination)
        guard installedSize == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(installedSize)",
            ])
        }
        let installedHash = try sha256Hex(for: destination)
        guard installedHash == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) sha256 mismatch: expected \(asset.sha256), got \(installedHash)",
            ])
        }
        return destination
    }

    private static func requireAsset(ref: String) throws -> UIWorldAsset {
        guard case let .loaded(document, _) = loadState() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "asset \(ref)"))
        }
        guard let asset = document.assets.asset(for: ref) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "asset \(ref)"))
        }
        return asset
    }

    private static func validatedSourceURL(for asset: UIWorldAsset, ref: String) throws -> URL {
        let url = URL(fileURLWithPath: asset.sourcePath)
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: url.path])
        }
        let size = try byteSize(for: url)
        guard size == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(size)",
            ])
        }
        let actual = try sha256Hex(for: url)
        guard actual == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World asset \(ref) sha256 mismatch: expected \(asset.sha256), got \(actual)",
            ])
        }
        return url
    }

    private static func installURL(for asset: UIWorldAsset, ref: String) throws -> URL {
        let installAs = asset.installAs.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !installAs.hasPrefix("/") else {
            preconditionFailure("UI World asset \(ref) installAs must be relative: \(installAs)")
        }
        let components = installAs.split(separator: "/").map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            preconditionFailure("UI World asset \(ref) installAs contains an unsafe path component: \(installAs)")
        }
        return FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(installAs)
    }

    static func sha256Hex(for url: URL) throws -> String {
        let data = try Data(contentsOf: url)
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func byteSize(for url: URL) throws -> Int {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let size = values.fileSize else {
            throw CocoaError(.fileReadUnknown, userInfo: [NSFilePathErrorKey: url.path])
        }
        return size
    }

    static func readerSeed(for fixtureID: UIWorldReaderFixtureID) -> UIWorldReaderSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.reader[fixtureID.rawValue]
    }

    static func requireReaderSeed(for fixtureID: UIWorldReaderFixtureID) -> UIWorldReaderSeed {
        guard let seed = readerSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "reader.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func vocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.vocabulary[fixtureID.rawValue]
    }

    static func requireVocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed {
        guard let seed = vocabularySeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "vocabulary.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func reviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.reviewDeck[fixtureID.rawValue]
    }

    static func requireReviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed {
        guard let seed = reviewDeckSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "reviewDeck.\(fixtureID.rawValue)"))
        }
        return seed
    }

    /// Decode a dataset document without going through the ambient load chain.
    /// Used by contract tests (and any tooling) to fail loudly on malformed
    /// UI World files.
    static func decode(_ data: Data) throws -> FixtureDatasetDocument {
        try makeDecoder().decode(FixtureDatasetDocument.self, from: data)
    }

    static func requireDocument() -> FixtureDatasetDocument {
        guard case let .loaded(document, _) = loadState() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "the UI World document"))
        }
        return document
    }

    /// Safe (non-`require`) accessor for the marketing capture domain. Returns
    /// nil when the UI World is absent/invalid or omits `marketingCapture`, so
    /// marketing catalog scenes can fall back gracefully in bare previews / QA
    /// worlds without a `preconditionFailure`.
    static func marketingCapture() -> MarketingCaptureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.marketingCapture
    }

    /// Diagnostic for `require*Seed` / asset resolution failures. When the UI
    /// World never loaded (missing env, invalid base64, decompress failure,
    /// decode error) the message must surface that root cause — reporting
    /// "missing <fixture key>" against a world that was never injected sends
    /// the investigation down the wrong path.
    static func seedResolutionFailureDescription(resolving reference: String) -> String {
        switch loadState() {
        case .loaded:
            return "UI World is missing \(reference)"
        case .absent:
            return "UI World is not loaded — neither \(fixtureDatasetDeflateEnvKey) nor \(fixtureDatasetEnvKey) is set (and no testing override); cannot resolve \(reference)"
        case let .invalid(source, error):
            return "UI World failed to load from \(source): \(error); cannot resolve \(reference)"
        }
    }

    static func debugSummary() -> String {
        switch loadState() {
        case .absent:
            return "absent"
        case let .invalid(source, error):
            return "invalid @ \(source) (\(error))"
        case let .loaded(document, source):
            return "\(document.datasetID) @ \(source)"
        }
    }

    private enum LoadState {
        case absent
        case invalid(source: String, error: String)
        case loaded(FixtureDatasetDocument, source: String)
    }

    private enum LoadSource {
        case absent
        case invalid(source: String, error: String)
        case data(Data, description: String)
    }

    private static func loadState() -> LoadState {
        let source = loadSource()
        switch source {
        case .absent:
            return .absent
        case let .invalid(source, error):
            return .invalid(source: source, error: error)
        case let .data(data, description):
            do {
                let document = try decode(data)
                return .loaded(document, source: description)
            } catch {
                return .invalid(source: description, error: String(reflecting: error))
            }
        }
    }

    private static func loadSource() -> LoadSource {
        if let testingOverrideData {
            return .data(testingOverrideData, description: "testing-override")
        }

        let environment = ProcessInfo.processInfo.environment
        let deflateRawValue = environment[fixtureDatasetDeflateEnvKey]
        let plainRawValue = environment[fixtureDatasetEnvKey]

        if deflateRawValue != nil, plainRawValue != nil {
            // Two sources could describe two different worlds; picking one
            // silently would hide exactly the kind of tooling drift this
            // fail-loud chain exists to expose.
            return .invalid(
                source: "env:\(fixtureDatasetDeflateEnvKey)+\(fixtureDatasetEnvKey)",
                error: "both \(fixtureDatasetDeflateEnvKey) and \(fixtureDatasetEnvKey) are set; the UI World source is ambiguous — unset one"
            )
        }

        if let deflateRawValue {
            let envDescription = "env:\(fixtureDatasetDeflateEnvKey)"
            guard !deflateRawValue.isEmpty else {
                return .invalid(source: envDescription, error: "\(fixtureDatasetDeflateEnvKey) must not be empty")
            }
            guard let compressed = Data(base64Encoded: deflateRawValue) else {
                return .invalid(source: envDescription, error: "\(fixtureDatasetDeflateEnvKey) is not valid base64")
            }
            do {
                let data = try (compressed as NSData).decompressed(using: .zlib) as Data
                return .data(data, description: envDescription)
            } catch {
                return .invalid(
                    source: envDescription,
                    error: "\(fixtureDatasetDeflateEnvKey) is not a raw DEFLATE stream (decompress failed: \(error.localizedDescription))"
                )
            }
        }

        let envDescription = "env:\(fixtureDatasetEnvKey)"
        guard let rawValue = plainRawValue else {
            return .absent
        }

        guard !rawValue.isEmpty else {
            return .invalid(source: envDescription, error: "\(fixtureDatasetEnvKey) must not be empty")
        }

        guard let data = Data(base64Encoded: rawValue) else {
            return .invalid(source: envDescription, error: "\(fixtureDatasetEnvKey) is not valid base64")
        }

        return .data(data, description: envDescription)
    }

    private static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            if let rawValue = try? container.decode(String.self) {
                if let date = AppDateFormatters.parseISO8601(rawValue) {
                    return date
                }
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "Expected ISO8601 date string, got \(rawValue)"
                )
            }
            if let rawValue = try? container.decode(Double.self) {
                return Date(timeIntervalSince1970: rawValue)
            }
            if let rawValue = try? container.decode(Int.self) {
                return Date(timeIntervalSince1970: TimeInterval(rawValue))
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Expected ISO8601 string or epoch seconds for Date"
            )
        }
        return decoder
    }
}

extension SubscriptionBadgeTone: Codable {
    private enum EncodedValue: String, Codable {
        case neutral
        case accent
        case success
    }

    init(from decoder: Decoder) throws {
        switch try EncodedValue(from: decoder) {
        case .neutral:
            self = .neutral
        case .accent:
            self = .accent
        case .success:
            self = .success
        }
    }

    func encode(to encoder: Encoder) throws {
        let encodedValue: EncodedValue
        switch self {
        case .neutral:
            encodedValue = .neutral
        case .accent:
            encodedValue = .accent
        case .success:
            encodedValue = .success
        }
        try encodedValue.encode(to: encoder)
    }
}

extension AutoplaySpeed: Codable {}

extension TodayReviewRevealStage: Codable {
    private enum EncodedValue: String, Codable {
        case front
        case back
    }

    init(from decoder: Decoder) throws {
        switch try EncodedValue(from: decoder) {
        case .front:
            self = .front
        case .back:
            self = .back
        }
    }

    func encode(to encoder: Encoder) throws {
        let encodedValue: EncodedValue = self == .front ? .front : .back
        try encodedValue.encode(to: encoder)
    }
}
