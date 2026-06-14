import Foundation

private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"

struct FixtureDatasetDocument: Decodable {
    let schema: String?
    let datasetID: String?
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

    init(
        schema: String? = nil,
        datasetID: String? = nil,
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
        auth = try container.decodeIfPresent([String: UIWorldAuthSeed].self, forKey: .auth) ?? [:]
        entitlements = try container.decodeIfPresent([String: UIWorldEntitlementsSeed].self, forKey: .entitlements) ?? [:]
        settings = try container.decodeIfPresent([String: SettingsFixtureSeed].self, forKey: .settings) ?? [:]
        bookshelf = try container.decodeIfPresent([String: BookshelfFixtureSeed].self, forKey: .bookshelf) ?? [:]
        todayReview = try container.decodeIfPresent([String: TodayReviewSessionSeed].self, forKey: .todayReview) ?? [:]
        notebook = try container.decodeIfPresent([String: NotebookFixtureSeed].self, forKey: .notebook) ?? [:]
        podcast = try container.decodeIfPresent([String: PodcastFixtureSeed].self, forKey: .podcast) ?? [:]
        runtimePodcast = try container.decodeIfPresent([String: UIWorldRuntimePodcastSeed].self, forKey: .runtimePodcast) ?? [:]
        reader = try container.decodeIfPresent([String: UIWorldReaderSeed].self, forKey: .reader) ?? [:]
        vocabulary = try container.decodeIfPresent([String: UIWorldVocabularySeed].self, forKey: .vocabulary) ?? [:]
        reviewDeck = try container.decodeIfPresent([String: UIWorldReviewDeckSeed].self, forKey: .reviewDeck) ?? [:]
    }
}

enum UIWorldAuthFixtureID: String, CaseIterable {
    case guest
    case signedIn
}

struct UIWorldAuthSeed: Codable, Equatable {
    let isLoggedIn: Bool
    let userId: String?
    let token: String?
    let displayName: String?
    let email: String?
    let provider: String?
    let providerUserId: String?
}

enum UIWorldEntitlementsFixtureID: String, CaseIterable {
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
    let remoteId: String
    let episodeNumber: Int
    let title: String
    let durationSec: Double?
    let audioAvailable: Bool
    let previewAvailable: Bool
    let previewDurationSec: Double?
    let subtitleAvailable: Bool
}

struct UIWorldRuntimePodcastSeed: Codable, Equatable {
    let audioPath: String
    let subtitlePath: String
    let seriesRemoteId: String
    let seriesTitle: String
    let hostNames: [String]
    let color: String?
    let coverPattern: String?
    let sortOrder: Int?
    let durationSec: Double
    let episodes: [UIWorldRuntimePodcastEpisodeSeed]
}

enum UIWorldReaderFixtureID: String, CaseIterable {
    case realBookLibrary
}

struct UIWorldReaderSeed: Codable, Equatable {
    let textPath: String
    let title: String
    let author: String
    let bookFileName: String
    let notebookRemoteId: String
    let notebookName: String
    let entry: UIWorldVocabularyEntrySeed
}

enum UIWorldVocabularyFixtureID: String, CaseIterable {
    case searchVocabNotebook
    case shellNavigation
}

struct UIWorldVocabularySeed: Codable, Equatable {
    let notebookRemoteId: String
    let notebookName: String
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
    case probe
    case notebookReviewDeck
}

struct UIWorldReviewDeckSeed: Codable, Equatable {
    let notebookRemoteId: String?
    let notebookName: String?
    let entries: [UIWorldVocabularyEntrySeed]
}

struct UIWorldVocabularyEntrySeed: Codable, Equatable {
    let word: String
    let translation: String
    let context: String
    let explanation: String?
    let partOfSpeech: String?
    let bookTitle: String?
    let chapterTitle: String?
    let kgCardId: String?
    let difficultyTier: String?
    let reviewMode: VocabularyCardMode?
    let reviewExamples: [String]
    let reviewIntervalHours: Double?
    let nextReviewAt: Date?
    let lastReviewedAt: Date?
    let reviewCount: Int?
    let reviewStreak: Int?
    let lastReviewFeedbackRaw: Int?
    let graphLinksByKind: [String: [KGCardLinkSummary]]
}

enum FixtureDatasetStore {
    static var testingOverrideData: Data?

    static func withTestingData<T>(_ data: Data?, perform: () throws -> T) rethrows -> T {
        let previous = testingOverrideData
        testingOverrideData = data
        defer { testingOverrideData = previous }
        return try perform()
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
