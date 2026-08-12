import Foundation
import CryptoKit

struct UIWorldScenarioContextSeed: Codable, Equatable {
    /// Optional anchor-day clock. `frozenEpoch` matches preferences
    /// `review_settings_progress_paused_at` when both are declared.
    let reviewClock: FixtureReviewClockSeed?
    /// Reader passage plus highlight words.
    let readerPassage: UIWorldReaderPassageSeed?
    /// Word Detail seed — `entries[0]` is the focused card, the
    /// rest are its graph-link targets. Reuses the vocabulary seed shape.
    let wordDetail: UIWorldVocabularySeed?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case reviewClock
        case readerPassage
        case wordDetail
    }

    init(
        reviewClock: FixtureReviewClockSeed? = nil,
        readerPassage: UIWorldReaderPassageSeed? = nil,
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
                    debugDescription: "UI World scenarioContext contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        reviewClock = try container.decodeIfPresent(FixtureReviewClockSeed.self, forKey: .reviewClock)
        readerPassage = try container.decodeIfPresent(UIWorldReaderPassageSeed.self, forKey: .readerPassage)
        wordDetail = try container.decodeIfPresent(UIWorldVocabularySeed.self, forKey: .wordDetail)
}
}
/// Frozen review clock. All fields are optional; when present, `frozenEpoch`
/// equals preferences
/// `review_settings_progress_paused_at`.
struct FixtureReviewClockSeed: Codable, Equatable {
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
                    debugDescription: "UI World scenarioContext.reviewClock contains unknown keys \(unknownKeys.sorted())"
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

/// Reader scenario passage. `activeWord` is the just-tapped word tied to the
/// translation overlay; it is guaranteed to appear as a token in `paragraphs`.
/// `activeWords == [activeWord]`.
struct UIWorldReaderPassageSeed: Codable, Equatable {
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
                    debugDescription: "UI World scenarioContext.readerPassage contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "UI World scenarioContext.readerPassage must explicitly declare \(key.rawValue)"
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
