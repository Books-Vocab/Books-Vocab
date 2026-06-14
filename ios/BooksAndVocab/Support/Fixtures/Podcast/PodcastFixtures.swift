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

    private static let continueSeries = PodcastSeriesSeed(
        remoteId: "s-shelf",
        title: "Atomic Habits Unpacked",
        hostNames: ["Ava Chen"],
        colorHex: NotebookPalette.defaultHex,
        coverPattern: NotebookCoverPattern.waves.rawValue
    )

    private static let registry = FixtureRegistry<PodcastFixtureSeed>([
        FixtureRecipe(key: PodcastFixtureID.shelfContinue.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
                series: continueSeries,
                episodes: [
                    .init(episodeNumber: 2, title: "On Deep Work", durationSec: 1832, lastPlayedTime: 612),
                    .init(
                        episodeNumber: 5,
                        title: "A Very Long Episode Title That Should Truncate Cleanly",
                        durationSec: 5432,
                        lastPlayedTime: 1700
                    ),
                    .init(episodeNumber: 8, title: "Marathon Session", durationSec: 12_345, lastPlayedTime: 321),
                    .init(episodeNumber: 1, title: "The Comfort Crisis", durationSec: 1832),
                ]
            )
        },
        FixtureRecipe(key: PodcastFixtureID.shelfSingle.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
                series: continueSeries,
                episodes: [
                    .init(episodeNumber: 2, title: "On Deep Work", durationSec: 1832, lastPlayedTime: 612),
                ]
            )
        },
    ])

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
