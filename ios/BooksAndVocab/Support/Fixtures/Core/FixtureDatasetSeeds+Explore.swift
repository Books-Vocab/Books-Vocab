#if os(iOS)
import Foundation

enum UIWorldExplorePhase: String, Codable, CaseIterable, Equatable {
    case loading
    case loaded
    case empty
    case error
}

enum UIWorldExploreFixtureID: String, Codable, CaseIterable, Equatable {
    case loading
    case loaded
    case empty
    case retry
    case emptyCounterexample = "empty-counterexample"
    case retryCounterexample = "retry-counterexample"

    var label: String {
        switch self {
        case .loading: return "explore-loading"
        case .loaded: return "explore-loaded"
        case .empty: return "explore-empty"
        case .retry: return "explore-retry"
        case .emptyCounterexample: return "explore-empty-counterexample"
        case .retryCounterexample: return "explore-retry-counterexample"
        }
    }

    var isCounterexample: Bool {
        switch self {
        case .emptyCounterexample, .retryCounterexample:
            return true
        case .loading, .loaded, .empty, .retry:
            return false
        }
    }

    static var required: [Self] { [.loading, .loaded, .empty, .retry] }
    static var counterexamples: [Self] { [.emptyCounterexample, .retryCounterexample] }

    static func assetSelector(for assetID: String) -> String {
        "explore.asset.\(assetID)"
    }
}

struct UIWorldExploreFixtureSeed: Codable, Equatable {
    let label: String
    let phase: UIWorldExplorePhase
    let retryPhase: UIWorldExplorePhase?
    let deckIDs: [String]
    let assetIDs: [String]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case label
        case phase
        case retryPhase
        case deckIDs
        case assetIDs
    }

    init(
        label: String,
        phase: UIWorldExplorePhase,
        retryPhase: UIWorldExplorePhase?,
        deckIDs: [String],
        assetIDs: [String]
    ) {
        self.label = label
        self.phase = phase
        self.retryPhase = retryPhase
        self.deckIDs = deckIDs
        self.assetIDs = assetIDs
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "Explore fixture contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "Explore fixture must explicitly declare \(key.rawValue)"
                )
            )
        }
        label = try container.decode(String.self, forKey: .label)
        phase = try container.decode(UIWorldExplorePhase.self, forKey: .phase)
        retryPhase = try container.decodeIfPresent(UIWorldExplorePhase.self, forKey: .retryPhase)
        deckIDs = try container.decode([String].self, forKey: .deckIDs)
        assetIDs = try container.decode([String].self, forKey: .assetIDs)
    }
}

struct UIWorldSharedDeckSeed: Codable, Equatable {
    let remoteId: String
    let title: String
    let authorLabel: String?
    let isOfficial: Bool
    let category: String?
    let languagePair: String?
    let tags: [String]
    let cardCount: Int
    let downloadCount: Int
    let ratingAvg: Double?
    let ratingCount: Int
    let color: String?
    let coverPattern: String?
    let updatedAt: String?
    let assetID: String?
    let sampleCards: [SharedDeckCard]?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case remoteId
        case title
        case authorLabel
        case isOfficial
        case category
        case languagePair
        case tags
        case cardCount
        case downloadCount
        case ratingAvg
        case ratingCount
        case color
        case coverPattern
        case updatedAt
        case assetID
        case sampleCards
    }

    init(
        remoteId: String,
        title: String,
        authorLabel: String? = nil,
        isOfficial: Bool = false,
        category: String? = nil,
        languagePair: String? = nil,
        tags: [String] = [],
        cardCount: Int = 0,
        downloadCount: Int = 0,
        ratingAvg: Double? = nil,
        ratingCount: Int = 0,
        color: String? = nil,
        coverPattern: String? = nil,
        updatedAt: String? = nil,
        assetID: String? = nil,
        sampleCards: [SharedDeckCard]? = nil
    ) {
        self.remoteId = remoteId
        self.title = title
        self.authorLabel = authorLabel
        self.isOfficial = isOfficial
        self.category = category
        self.languagePair = languagePair
        self.tags = tags
        self.cardCount = cardCount
        self.downloadCount = downloadCount
        self.ratingAvg = ratingAvg
        self.ratingCount = ratingCount
        self.color = color
        self.coverPattern = coverPattern
        self.updatedAt = updatedAt
        self.assetID = assetID
        self.sampleCards = sampleCards
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "Explore deck seed contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }

        let container = try decoder.container(keyedBy: CodingKeys.self)
        remoteId = try container.decode(String.self, forKey: .remoteId)
        title = try container.decode(String.self, forKey: .title)
        authorLabel = try container.decodeIfPresent(String.self, forKey: .authorLabel)
        isOfficial = try container.decodeIfPresent(Bool.self, forKey: .isOfficial) ?? false
        category = try container.decodeIfPresent(String.self, forKey: .category)
        languagePair = try container.decodeIfPresent(String.self, forKey: .languagePair)
        tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
        cardCount = try container.decodeIfPresent(Int.self, forKey: .cardCount) ?? 0
        downloadCount = try container.decodeIfPresent(Int.self, forKey: .downloadCount) ?? 0
        ratingAvg = try container.decodeIfPresent(Double.self, forKey: .ratingAvg)
        ratingCount = try container.decodeIfPresent(Int.self, forKey: .ratingCount) ?? 0
        color = try container.decodeIfPresent(String.self, forKey: .color)
        coverPattern = try container.decodeIfPresent(String.self, forKey: .coverPattern)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
        assetID = try container.decodeIfPresent(String.self, forKey: .assetID)
        sampleCards = try container.decodeIfPresent([SharedDeckCard].self, forKey: .sampleCards)
    }

    var productionSummary: SharedDeckSummary {
        SharedDeckSummary(
            deckId: remoteId,
            title: title,
            color: color,
            coverPattern: coverPattern,
            authorLabel: authorLabel,
            isOfficial: isOfficial,
            cardCount: cardCount,
            downloadCount: downloadCount,
            ratingAvg: ratingAvg,
            ratingCount: ratingCount,
            languagePair: languagePair,
            category: category,
            tags: tags,
            updatedAt: updatedAt
        )
    }
}

enum UIWorldSharedDeckCatalogContractError: Error, Equatable, CustomStringConvertible {
    case invalid(String)

    var description: String {
        switch self {
        case .invalid(let message): return message
        }
    }
}

struct UIWorldSharedDeckCatalogSeed: Codable, Equatable {
    let fixtures: [String: UIWorldExploreFixtureSeed]
    let decks: [String: UIWorldSharedDeckSeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case fixtures
        case decks
    }

    init(
        fixtures: [String: UIWorldExploreFixtureSeed],
        decks: [String: UIWorldSharedDeckSeed]
    ) throws {
        self.fixtures = fixtures
        self.decks = decks
        try validate()
    }

    init(from decoder: Decoder) throws {
        let rawContainer = try decoder.container(keyedBy: AnyCodingKey.self)
        let unknownKeys = Set(rawContainer.allKeys.map(\.stringValue))
            .subtracting(CodingKeys.allCases.map(\.rawValue))
        guard unknownKeys.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "sharedDecks contains unknown keys \(unknownKeys.sorted())"
                )
            )
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        fixtures = try container.decode([String: UIWorldExploreFixtureSeed].self, forKey: .fixtures)
        decks = try container.decode([String: UIWorldSharedDeckSeed].self, forKey: .decks)
        try validate()
    }

    var requiredFixtureLabels: [String] {
        UIWorldExploreFixtureID.required.compactMap { fixtures[$0.rawValue]?.label }
    }

    var counterexampleFixtureLabels: [String] {
        UIWorldExploreFixtureID.counterexamples.compactMap { fixtures[$0.rawValue]?.label }
    }

    var requiredAssetIDs: Set<String> {
        assetIDs(for: UIWorldExploreFixtureID.required)
    }

    var counterexampleAssetIDs: Set<String> {
        assetIDs(for: UIWorldExploreFixtureID.counterexamples)
    }

    var requiredDeckIDs: Set<String> {
        deckIDs(for: UIWorldExploreFixtureID.required)
    }

    var counterexampleDeckIDs: Set<String> {
        deckIDs(for: UIWorldExploreFixtureID.counterexamples)
    }

    /// Canonical projection consumed by the generic scenario context. Keep
    /// this aligned with `ops/ui_world_manifest.py`'s
    /// `_expected_explore_surface_projection`: top-level sharedDecks owns the
    /// fixture order and the generic surface contract is only a projection.
    var canonicalExploreSurfaceContract: UIWorldSurfaceContractSeed {
        UIWorldSurfaceContractSeed(
            required: projectionRows(for: UIWorldExploreFixtureID.required),
            counterexamples: projectionRows(
                for: UIWorldExploreFixtureID.counterexamples,
                indexOffset: UIWorldExploreFixtureID.required.count
            )
        )
    }

    func fixture(for id: UIWorldExploreFixtureID) -> UIWorldExploreFixtureSeed {
        guard let fixture = fixtures[id.rawValue] else {
            preconditionFailure("UI World is missing sharedDecks fixture \(id.rawValue)")
        }
        return fixture
    }

    func deck(for remoteId: String) -> UIWorldSharedDeckSeed? {
        decks[remoteId]
    }

    func validateAssets(_ assets: UIWorldAssetManifest) throws {
        let refs = Set(fixtures.values.flatMap(\.assetIDs))
            .union(decks.values.compactMap(\.assetID))
        let missing = refs.filter { assets.asset(for: $0) == nil }.sorted()
        guard missing.isEmpty else {
            throw UIWorldSharedDeckCatalogContractError.invalid(
                "sharedDecks references assets absent from the UI World asset manifest: \(missing)"
            )
        }
    }

    private func assetIDs(for ids: [UIWorldExploreFixtureID]) -> Set<String> {
        Set(ids.flatMap { fixtures[$0.rawValue]?.assetIDs ?? [] })
    }

    private func deckIDs(for ids: [UIWorldExploreFixtureID]) -> Set<String> {
        Set(ids.flatMap { fixtures[$0.rawValue]?.deckIDs ?? [] })
    }

    private func projectionRows(
        for ids: [UIWorldExploreFixtureID],
        indexOffset: Int = 0
    ) -> [UIWorldSurfaceContractRowSeed] {
        ids.enumerated().map { offset, id in
            let fixture = fixture(for: id)
            let rawAssetIDs = fixture.assetIDs.map { ref in
                guard let separator = ref.firstIndex(of: ".") else {
                    preconditionFailure("sharedDecks asset ref must include a manifest bucket: \(ref)")
                }
                return String(ref[ref.index(after: separator)...])
            }
            return UIWorldSurfaceContractRowSeed(
                fixtureID: id.rawValue,
                stepLabel: fixture.label,
                index: offset + indexOffset,
                assetIDs: rawAssetIDs
            )
        }
    }

    private func validate() throws {
        let expectedIDs = Set(UIWorldExploreFixtureID.allCases.map(\.rawValue))
        let actualIDs = Set(fixtures.keys)
        guard actualIDs == expectedIDs else {
            throw UIWorldSharedDeckCatalogContractError.invalid(
                "sharedDecks fixture IDs drifted; expected \(expectedIDs.sorted()), got \(actualIDs.sorted())"
            )
        }

        for id in UIWorldExploreFixtureID.allCases {
            guard let fixture = fixtures[id.rawValue] else { continue }
            guard fixture.label == id.label else {
                throw UIWorldSharedDeckCatalogContractError.invalid(
                    "sharedDecks fixture \(id.rawValue) must use label \(id.label), got \(fixture.label)"
                )
            }
            guard !fixture.assetIDs.isEmpty, Set(fixture.assetIDs).count == fixture.assetIDs.count else {
                throw UIWorldSharedDeckCatalogContractError.invalid(
                    "sharedDecks fixture \(id.rawValue) must have unique non-empty assetIDs"
                )
            }
            guard Set(fixture.deckIDs).count == fixture.deckIDs.count else {
                throw UIWorldSharedDeckCatalogContractError.invalid(
                    "sharedDecks fixture \(id.rawValue) must have unique deckIDs"
                )
            }
            switch id {
            case .loading:
                guard fixture.phase == .loading, fixture.retryPhase == nil else {
                    throw invalidPhase(id)
                }
            case .loaded:
                guard fixture.phase == .loaded, fixture.retryPhase == nil, !fixture.deckIDs.isEmpty else {
                    throw invalidPhase(id)
                }
            case .empty, .emptyCounterexample:
                guard fixture.phase == .empty, fixture.retryPhase == nil, fixture.deckIDs.isEmpty else {
                    throw invalidPhase(id)
                }
            case .retry, .retryCounterexample:
                guard fixture.phase == .error, fixture.retryPhase == .loaded, !fixture.deckIDs.isEmpty else {
                    throw invalidPhase(id)
                }
            }
        }

        let requiredDeckIDs = deckIDs(for: UIWorldExploreFixtureID.required)
        let counterexampleDeckIDs = deckIDs(for: UIWorldExploreFixtureID.counterexamples)
        guard requiredDeckIDs.isDisjoint(with: counterexampleDeckIDs) else {
            throw UIWorldSharedDeckCatalogContractError.invalid(
                "sharedDecks required and counterexample deck IDs must be disjoint"
            )
        }
        guard requiredAssetIDs.isDisjoint(with: counterexampleAssetIDs) else {
            throw UIWorldSharedDeckCatalogContractError.invalid(
                "sharedDecks required and counterexample asset IDs must be disjoint"
            )
        }

        let referencedDeckIDs = requiredDeckIDs.union(counterexampleDeckIDs)
        guard Set(decks.keys) == referencedDeckIDs else {
            throw UIWorldSharedDeckCatalogContractError.invalid(
                "sharedDecks deck map must exactly match fixture references"
            )
        }
        for id in UIWorldExploreFixtureID.allCases {
            guard let fixture = fixtures[id.rawValue] else { continue }
            for remoteId in fixture.deckIDs {
                guard let deck = decks[remoteId] else {
                    throw UIWorldSharedDeckCatalogContractError.invalid(
                        "sharedDecks fixture \(id.rawValue) references missing deck \(remoteId)"
                    )
                }
                guard let assetID = deck.assetID, fixture.assetIDs.contains(assetID) else {
                    throw UIWorldSharedDeckCatalogContractError.invalid(
                        "sharedDecks deck \(remoteId) must map to an assetID in fixture \(id.rawValue)"
                    )
                }
            }
        }
    }

    private func invalidPhase(_ id: UIWorldExploreFixtureID) -> UIWorldSharedDeckCatalogContractError {
        .invalid(
            "sharedDecks fixture \(id.rawValue) has an invalid phase/deck mapping"
        )
    }
}
#endif
