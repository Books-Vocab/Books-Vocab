#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedPodcast(_ id: String, into container: ModelContainer) {
        switch id {
        case "playablePreview":
            seedPlayablePodcastPreview(into: container)
        default:
            failFixtureSeed("Unknown podcast fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedPlayablePodcastPreview(into container: ModelContainer) {
        let context = container.mainContext
        do {
            try clearPodcastFixtures(from: context)

            let fixture = try resolvePlayablePodcastFixture(.playablePreview)
            let subtitle = try String(contentsOf: fixture.subtitleURL, encoding: .utf8)
            let series = PodcastSeries(
                remoteId: fixture.seed.seriesRemoteId,
                title: fixture.seriesTitle,
                hostNames: fixture.hostNames
            )
            series.color = fixture.seed.color
            series.coverPattern = fixture.seed.coverPattern
            series.episodeCount = fixture.seed.episodes.count
            series.totalDurationSec = fixture.durationSec
            series.sortOrder = fixture.seed.sortOrder
            series.isFollowed = false

            for episodeSeed in fixture.seed.episodes {
                let download = try materializeDownload(for: episodeSeed)
                let episode = PodcastEpisode(
                    remoteId: episodeSeed.remoteId,
                    episodeNumber: episodeSeed.episodeNumber,
                    title: episodeSeed.title,
                    durationSec: episodeSeed.durationSec
                )
                episode.series = series
                episode.audioAvailable = episodeSeed.audioAvailable
                episode.previewAvailable = episodeSeed.previewAvailable
                episode.previewDurationSec = episodeSeed.previewDurationSec
                episode.localAudioPath = download.audioURL?.path
                episode.localSubtitlePath = download.subtitleURL?.path
                episode.subtitleAvailable = episodeSeed.subtitleAvailable
                episode.inlineSubtitle = subtitle
                context.insert(episode)
            }

            context.insert(series)
            try context.save()
            seedSignedInLoginFromWorld()
            AppLog.app.info("UI-test fixture seeded: podcast.playablePreview")
        } catch {
            failFixtureSeed("Failed to seed podcast.playablePreview fixture: \(error)")
        }
    }

    private struct PlayablePodcastFixture {
        let seed: UIWorldRuntimePodcastSeed
        let audioURL: URL
        let subtitleURL: URL
        let durationSec: Double
        let seriesTitle: String
        let hostNames: [String]
    }

    @MainActor
    private static func clearPodcastFixtures(from context: ModelContext) throws {
        for progress in try context.fetch(FetchDescriptor<PodcastProgress>()) {
            context.delete(progress)
        }
        for episode in try context.fetch(FetchDescriptor<PodcastEpisode>()) {
            context.delete(episode)
        }
        for series in try context.fetch(FetchDescriptor<PodcastSeries>()) {
            context.delete(series)
        }
        try context.save()
    }

    private static func resolvePlayablePodcastFixture(_ fixtureID: UIWorldRuntimePodcastFixtureID) throws -> PlayablePodcastFixture {
        let seed = FixtureDatasetStore.requireRuntimePodcastSeed(for: fixtureID)
        let audioURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: seed.audioAssetRef)
        let subtitleURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: seed.subtitleAssetRef)
        return PlayablePodcastFixture(
            seed: seed,
            audioURL: audioURL,
            subtitleURL: subtitleURL,
            durationSec: seed.durationSec,
            seriesTitle: seed.seriesTitle,
            hostNames: seed.hostNames
        )
    }

    private struct MaterializedEpisodeDownload {
        let audioURL: URL?
        let subtitleURL: URL?
    }

    private static func materializeDownload(
        for episode: UIWorldRuntimePodcastEpisodeSeed
    ) throws -> MaterializedEpisodeDownload {
        guard let download = episode.download else {
            return MaterializedEpisodeDownload(audioURL: nil, subtitleURL: nil)
        }
        let audioURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: download.audioAssetRef)
        let subtitleURL = try download.subtitleAssetRef.map {
            try FixtureDatasetStore.requireInstalledAssetURL(ref: $0)
        }
        return MaterializedEpisodeDownload(audioURL: audioURL, subtitleURL: subtitleURL)
    }
}
#endif
