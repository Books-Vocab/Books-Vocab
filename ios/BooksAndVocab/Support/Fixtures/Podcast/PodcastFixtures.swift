#if os(iOS)
import Foundation

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
}

struct PodcastEpisodeSeed: Codable {
    let episodeNumber: Int
    let title: String
    let durationSec: Double
    /// Seconds already played; `nil` renders the episode as unstarted (no progress row).
    var lastPlayedTime: Double?
}

struct PodcastFixtureSeed: Codable {
    let series: PodcastSeriesSeed
    let episodes: [PodcastEpisodeSeed]
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
