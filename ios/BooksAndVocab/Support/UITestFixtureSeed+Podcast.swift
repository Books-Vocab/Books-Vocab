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
            AppLog.app.warning("Unknown podcast fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedPlayablePodcastPreview(into container: ModelContainer) {
        let context = container.mainContext
        do {
            try clearPodcastFixtures(from: context)

            let fixture = try resolvePlayablePodcastFixture(.playablePreview)
            let audioURL = try copyFixtureFileToTemporaryDirectory(
                source: fixture.audioURL,
                fileName: "kg-uitest-\(fixture.audioURL.lastPathComponent)"
            )
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
            series.sortOrder = fixture.seed.sortOrder ?? 0
            series.isFollowed = false

            for episodeSeed in fixture.seed.episodes {
                let episode = PodcastEpisode(
                    remoteId: episodeSeed.remoteId,
                    episodeNumber: episodeSeed.episodeNumber,
                    title: episodeSeed.title,
                    durationSec: episodeSeed.durationSec ?? fixture.durationSec
                )
                episode.series = series
                episode.audioAvailable = episodeSeed.audioAvailable
                episode.previewAvailable = episodeSeed.previewAvailable
                episode.previewDurationSec = episodeSeed.previewDurationSec ?? 0
                episode.localAudioPath = audioURL.path
                episode.subtitleAvailable = episodeSeed.subtitleAvailable
                episode.inlineSubtitle = subtitle
                context.insert(episode)
            }

            context.insert(series)
            try context.save()
            seedSignedInLoginFromWorld()
            AppLog.app.info("UI-test fixture seeded: podcast.playablePreview")
        } catch {
            AppLog.app.error("Failed to seed podcast fixture: \(error)")
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
        let audioURL = URL(fileURLWithPath: seed.audioPath)
        let subtitleURL = URL(fileURLWithPath: seed.subtitlePath)
        guard FileManager.default.fileExists(atPath: audioURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: audioURL.path])
        }
        guard FileManager.default.fileExists(atPath: subtitleURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: subtitleURL.path])
        }
        return PlayablePodcastFixture(
            seed: seed,
            audioURL: audioURL,
            subtitleURL: subtitleURL,
            durationSec: seed.durationSec,
            seriesTitle: seed.seriesTitle,
            hostNames: seed.hostNames
        )
    }

    private static func copyFixtureFileToTemporaryDirectory(source: URL, fileName: String) throws -> URL {
        let destination = FileManager.default.temporaryDirectory.appendingPathComponent(fileName)
        if FileManager.default.fileExists(atPath: destination.path) {
            try FileManager.default.removeItem(at: destination)
        }
        try FileManager.default.copyItem(at: source, to: destination)
        return destination
    }
}
#endif
