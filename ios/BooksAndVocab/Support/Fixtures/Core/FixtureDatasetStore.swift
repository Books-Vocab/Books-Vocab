import Foundation
import CryptoKit

private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"

struct FixtureDatasetDocument: Decodable {
    let schema: String?
    let datasetID: String?
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
    }

    /// Single source of truth for the top-level key set. Keyed decoding
    /// silently ignores unknown keys, so contract tests diff a dataset's raw
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
    ]

    init(
        schema: String? = nil,
        datasetID: String? = nil,
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
        reviewDeck: [String: UIWorldReviewDeckSeed] = [:]
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
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schema = try container.decodeIfPresent(String.self, forKey: .schema)
        datasetID = try container.decodeIfPresent(String.self, forKey: .datasetID)
        let isV2 = schema == "kg.fixture.dataset.v2"
        if isV2 {
            for key in Self.requiredV2DomainKeys where !container.contains(key) {
                throw DecodingError.keyNotFound(
                    key,
                    DecodingError.Context(
                        codingPath: container.codingPath,
                        debugDescription: "UI World v2 must explicitly declare top-level \(key.rawValue)"
                    )
                )
            }
        }
        assets = isV2 ? try container.decode(UIWorldAssetManifest.self, forKey: .assets) : try container.decodeIfPresent(UIWorldAssetManifest.self, forKey: .assets) ?? .empty
        preferences = isV2 ? try container.decode(UIWorldPreferencesSeed.self, forKey: .preferences) : try container.decodeIfPresent(UIWorldPreferencesSeed.self, forKey: .preferences) ?? .empty
        auth = isV2 ? try container.decode([String: UIWorldAuthSeed].self, forKey: .auth) : try container.decodeIfPresent([String: UIWorldAuthSeed].self, forKey: .auth) ?? [:]
        entitlements = isV2 ? try container.decode([String: UIWorldEntitlementsSeed].self, forKey: .entitlements) : try container.decodeIfPresent([String: UIWorldEntitlementsSeed].self, forKey: .entitlements) ?? [:]
        settings = isV2 ? try container.decode([String: SettingsFixtureSeed].self, forKey: .settings) : try container.decodeIfPresent([String: SettingsFixtureSeed].self, forKey: .settings) ?? [:]
        bookshelf = isV2 ? try container.decode([String: BookshelfFixtureSeed].self, forKey: .bookshelf) : try container.decodeIfPresent([String: BookshelfFixtureSeed].self, forKey: .bookshelf) ?? [:]
        todayReview = isV2 ? try container.decode([String: TodayReviewSessionSeed].self, forKey: .todayReview) : try container.decodeIfPresent([String: TodayReviewSessionSeed].self, forKey: .todayReview) ?? [:]
        notebook = isV2 ? try container.decode([String: NotebookFixtureSeed].self, forKey: .notebook) : try container.decodeIfPresent([String: NotebookFixtureSeed].self, forKey: .notebook) ?? [:]
        podcast = isV2 ? try container.decode([String: PodcastFixtureSeed].self, forKey: .podcast) : try container.decodeIfPresent([String: PodcastFixtureSeed].self, forKey: .podcast) ?? [:]
        runtimePodcast = isV2 ? try container.decode([String: UIWorldRuntimePodcastSeed].self, forKey: .runtimePodcast) : try container.decodeIfPresent([String: UIWorldRuntimePodcastSeed].self, forKey: .runtimePodcast) ?? [:]
        reader = isV2 ? try container.decode([String: UIWorldReaderSeed].self, forKey: .reader) : try container.decodeIfPresent([String: UIWorldReaderSeed].self, forKey: .reader) ?? [:]
        vocabulary = isV2 ? try container.decode([String: UIWorldVocabularySeed].self, forKey: .vocabulary) : try container.decodeIfPresent([String: UIWorldVocabularySeed].self, forKey: .vocabulary) ?? [:]
        reviewDeck = isV2 ? try container.decode([String: UIWorldReviewDeckSeed].self, forKey: .reviewDeck) : try container.decodeIfPresent([String: UIWorldReviewDeckSeed].self, forKey: .reviewDeck) ?? [:]
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
    let userDefaults: [String: UIWorldPreferenceValue]
    let ubiquitousKeyValueStore: [String: UIWorldPreferenceValue]

    static let empty = UIWorldPreferencesSeed(userDefaults: [:], ubiquitousKeyValueStore: [:])

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
    let installAs: String?
}

struct UIWorldAssetManifest: Codable, Equatable {
    let books: [String: UIWorldAsset]
    let audio: [String: UIWorldAsset]
    let subtitles: [String: UIWorldAsset]
    let text: [String: UIWorldAsset]
    let images: [String: UIWorldAsset]

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
}

enum UIWorldAuthFixtureID: String, CaseIterable {
    case guest
    case signedIn
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
    let provider: String?
    let providerUserId: String?
}

enum UIWorldEntitlementsFixtureID: String, CaseIterable {
    case adminGranted
    case cancelledButActive
    case free
    case pro
}

struct UIWorldEntitlementsSeed: Codable, Equatable {
    let pro: KGSubscriptionStatus
}

enum UIWorldRuntimePodcastFixtureID: String, CaseIterable {
    case playablePreview
    case tieredCatalog
}

struct UIWorldRuntimePodcastEpisodeSeed: Codable, Equatable {
    struct Download: Codable, Equatable {
        let audioAssetRef: String
        let subtitleAssetRef: String?
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
}

struct UIWorldRuntimePodcastSeed: Codable, Equatable {
    let audioAssetRef: String
    let subtitleAssetRef: String
    let seriesRemoteId: String
    let seriesTitle: String
    let hostNames: [String]
    let color: String?
    let coverPattern: String?
    let sortOrder: Int
    let durationSec: Double
    let episodes: [UIWorldRuntimePodcastEpisodeSeed]
}

enum UIWorldReaderFixtureID: String, CaseIterable {
    case realBookLibrary
}

struct UIWorldReaderSeed: Codable, Equatable {
    let textAssetRef: String
    let title: String
    let author: String
    let bookFileName: String
    let notebookRemoteId: String
    let notebookName: String
    let notebookSyncStatus: Int
    let entry: UIWorldVocabularyEntrySeed
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
}

struct UIWorldReviewHistorySeed: Codable, Equatable {
    let word: String
    let feedback: Int
    let reviewedAt: Date
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
            preconditionFailure("UI World is missing settings.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func authSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.auth[fixtureID.rawValue]
    }

    static func requireAuthSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed {
        guard let seed = authSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing auth.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func entitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.entitlements[fixtureID.rawValue]
    }

    static func requireEntitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed {
        guard let seed = entitlementsSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing entitlements.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func bookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.bookshelf[fixtureID.rawValue]
    }

    static func requireBookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed {
        guard let seed = bookshelfSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing bookshelf.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func todayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.todayReview[fixtureID.rawValue]
    }

    static func requireTodayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed {
        guard let seed = todayReviewSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing todayReview.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func notebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.notebook[fixtureID.rawValue]
    }

    static func requireNotebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed {
        guard let seed = notebookSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing notebook.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func podcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.podcast[fixtureID.rawValue]
    }

    static func requirePodcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed {
        guard let seed = podcastSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing podcast.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func runtimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.runtimePodcast[fixtureID.rawValue]
    }

    static func requireRuntimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed {
        guard let seed = runtimePodcastSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing runtimePodcast.\(fixtureID.rawValue)")
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
            preconditionFailure("UI World is not loaded; asset \(ref) cannot resolve")
        }
        guard let asset = document.assets.asset(for: ref) else {
            preconditionFailure("UI World is missing asset \(ref)")
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
        guard let installAs = asset.installAs?.trimmingCharacters(in: .whitespacesAndNewlines),
              !installAs.isEmpty else {
            preconditionFailure("UI World asset \(ref) is missing installAs")
        }
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
            preconditionFailure("UI World is missing reader.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func vocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.vocabulary[fixtureID.rawValue]
    }

    static func requireVocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed {
        guard let seed = vocabularySeed(for: fixtureID) else {
            preconditionFailure("UI World is missing vocabulary.\(fixtureID.rawValue)")
        }
        return seed
    }

    static func reviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.reviewDeck[fixtureID.rawValue]
    }

    static func requireReviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed {
        guard let seed = reviewDeckSeed(for: fixtureID) else {
            preconditionFailure("UI World is missing reviewDeck.\(fixtureID.rawValue)")
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
            preconditionFailure("UI World is not loaded")
        }
        return document
    }

    static func debugSummary() -> String {
        switch loadState() {
        case .absent:
            return "absent"
        case let .invalid(source, error):
            return "invalid @ \(source) (\(error))"
        case let .loaded(document, source):
            return "\(document.datasetID ?? "<no-id>") @ \(source)"
        }
    }

    private enum LoadState {
        case absent
        case invalid(source: String, error: String)
        case loaded(FixtureDatasetDocument, source: String)
    }

    private static func loadState() -> LoadState {
        guard let source = loadSource() else { return .absent }
        do {
            let document = try decode(source.data)
            return .loaded(document, source: source.description)
        } catch {
            return .invalid(source: source.description, error: String(reflecting: error))
        }
    }

    private static func loadSource() -> (data: Data, description: String)? {
        if let testingOverrideData {
            return (testingOverrideData, "testing-override")
        }

        // Empty value counts as absent (defensive): `Data(base64Encoded: "")`
        // is empty Data, not nil, so a stray empty export would otherwise land
        // in `.invalid`.
        if let rawValue = ProcessInfo.processInfo.environment[fixtureDatasetEnvKey],
           !rawValue.isEmpty,
           let data = Data(base64Encoded: rawValue) {
            return (data, "env:\(fixtureDatasetEnvKey)")
        }

        return nil
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
