#if os(iOS)
import Foundation

private struct AnyPodcastCodingKey: CodingKey {
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

private func rejectUnknownPodcastKeys<Key>(
    from decoder: Decoder,
    knownKeys: Key.Type,
    context: String
) throws where Key: CodingKey & CaseIterable, Key.AllCases: Sequence {
    let rawContainer = try decoder.container(keyedBy: AnyPodcastCodingKey.self)
    let known = Set(Key.allCases.map(\.stringValue))
    let unknown = Set(rawContainer.allKeys.map(\.stringValue)).subtracting(known)
    guard unknown.isEmpty else {
        throw DecodingError.dataCorrupted(
            .init(
                codingPath: decoder.codingPath,
                debugDescription: "\(context) contains unknown keys \(unknown.sorted())"
            )
        )
    }
}

private func requireAllPodcastKeys<Key>(
    in container: KeyedDecodingContainer<Key>,
    context: String
) throws where Key: CodingKey & CaseIterable, Key.AllCases: Sequence {
    for key in Key.allCases where !container.contains(key) {
        throw DecodingError.keyNotFound(
            key,
            .init(
                codingPath: container.codingPath,
                debugDescription: "\(context) must explicitly declare \(key.stringValue), even when null"
            )
        )
    }
}

enum PodcastFixtureID: String, CaseIterable {
    case shelfContinue = "shelf_continue"
    case shelfSingle = "shelf_single"

    var key: FixtureKey {
        FixtureKey("podcast.\(rawValue)")
    }
}

struct PodcastSeriesSeed: Codable {
    let remoteId: String
    let title: String
    let hostNames: [String]
    var colorHex: String?
    var coverPattern: String?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case remoteId
        case title
        case hostNames
        case colorHex
        case coverPattern
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownPodcastKeys(from: decoder, knownKeys: CodingKeys.self, context: "UI World podcast series")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireAllPodcastKeys(in: container, context: "UI World podcast series")
        remoteId = try container.decode(String.self, forKey: .remoteId)
        title = try container.decode(String.self, forKey: .title)
        hostNames = try container.decode([String].self, forKey: .hostNames)
        colorHex = try container.decodeIfPresent(String.self, forKey: .colorHex)
        coverPattern = try container.decodeIfPresent(String.self, forKey: .coverPattern)
    }
}

struct PodcastEpisodeSeed: Codable {
    let episodeNumber: Int
    let title: String
    let durationSec: Double
    /// Seconds already played; `nil` renders the episode as unstarted (no progress row).
    var lastPlayedTime: Double?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case episodeNumber
        case title
        case durationSec
        case lastPlayedTime
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownPodcastKeys(from: decoder, knownKeys: CodingKeys.self, context: "UI World podcast episode")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireAllPodcastKeys(in: container, context: "UI World podcast episode")
        episodeNumber = try container.decode(Int.self, forKey: .episodeNumber)
        title = try container.decode(String.self, forKey: .title)
        durationSec = try container.decode(Double.self, forKey: .durationSec)
        lastPlayedTime = try container.decodeIfPresent(Double.self, forKey: .lastPlayedTime)
    }
}

struct PodcastFixtureSeed: Codable {
    let series: PodcastSeriesSeed
    let episodes: [PodcastEpisodeSeed]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case series
        case episodes
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownPodcastKeys(from: decoder, knownKeys: CodingKeys.self, context: "UI World podcast fixture")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireAllPodcastKeys(in: container, context: "UI World podcast fixture")
        series = try container.decode(PodcastSeriesSeed.self, forKey: .series)
        episodes = try container.decode([PodcastEpisodeSeed].self, forKey: .episodes)
    }
}

struct PodcastShelfItemRenderModel {
    let episode: PodcastEpisode
    let progress: PodcastProgress?
}

struct PodcastFixtureRenderModel {
    let series: PodcastSeries
    let items: [PodcastShelfItemRenderModel]
}

enum PodcastFixtures {
    private static let sharedSurfaces: Set<FixtureSurface> = [.preview, .catalog, .snapshot]

    private static let registry = FixtureRegistry<PodcastFixtureSeed>(
        PodcastFixtureID.allCases.map { fixtureID in
            FixtureRecipe(key: fixtureID.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
                FixtureDatasetStore.requirePodcastSeed(for: fixtureID)
            }
        }
    )

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<PodcastFixtureSeed>] {
        registry.recipes(for: surface)
    }

    @MainActor
    static func renderModel(for fixtureID: PodcastFixtureID) -> PodcastFixtureRenderModel {
        let seed = FixtureDatasetStore.requirePodcastSeed(for: fixtureID)

        let series = PodcastSeries(
            remoteId: seed.series.remoteId,
            title: seed.series.title,
            hostNames: seed.series.hostNames
        )
        if let colorHex = seed.series.colorHex {
            series.color = colorHex
        }
        if let coverPattern = seed.series.coverPattern {
            series.coverPattern = coverPattern
        }

        let items = seed.episodes.map { episodeSeed -> PodcastShelfItemRenderModel in
            let episodeRemoteId = "\(seed.series.remoteId)_ep_\(episodeSeed.episodeNumber)"
            let episode = PodcastEpisode(
                remoteId: episodeRemoteId,
                episodeNumber: episodeSeed.episodeNumber,
                title: episodeSeed.title,
                durationSec: episodeSeed.durationSec
            )
            let progress = episodeSeed.lastPlayedTime.map {
                PodcastProgress(episodeRemoteId: episodeRemoteId, lastPlayedTime: $0)
            }
            return .init(episode: episode, progress: progress)
        }

        return .init(series: series, items: items)
    }
}
#endif
