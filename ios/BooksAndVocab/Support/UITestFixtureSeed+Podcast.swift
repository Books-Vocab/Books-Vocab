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

            let fixture = try resolvePlayablePodcastFixture()
            let audioURL = try copyFixtureFileToTemporaryDirectory(
                source: fixture.audioURL,
                fileName: "kg-uitest-\(fixture.audioURL.lastPathComponent)"
            )
            let subtitle = try String(contentsOf: fixture.subtitleURL, encoding: .utf8)
            let series = PodcastSeries(
                remoteId: "ui-playable-series",
                title: fixture.seriesTitle,
                hostNames: fixture.hostNames
            )
            series.color = "sunset"
            series.coverPattern = "waves"
            series.episodeCount = 1
            series.totalDurationSec = fixture.durationSec
            series.sortOrder = -10_000
            series.isFollowed = false

            let episode = PodcastEpisode(
                remoteId: "ui-playable-series_ep_01",
                episodeNumber: 1,
                title: fixture.episodeTitle,
                durationSec: fixture.durationSec
            )
            episode.series = series
            episode.audioAvailable = true
            episode.previewAvailable = true
            episode.previewDurationSec = min(fixture.durationSec, 180)
            episode.localAudioPath = audioURL.path
            episode.subtitleAvailable = true
            episode.inlineSubtitle = subtitle

            context.insert(series)
            context.insert(episode)
            try context.save()
            seedSignedInLoginFromWorld()
            AppLog.app.info("UI-test fixture seeded: podcast.playablePreview")
        } catch {
            AppLog.app.error("Failed to seed podcast fixture: \(error)")
        }
    }

    private struct PlayablePodcastFixture {
        let audioURL: URL
        let subtitleURL: URL
        let durationSec: Double
        let seriesTitle: String
        let episodeTitle: String
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

    private static func resolvePlayablePodcastFixture() throws -> PlayablePodcastFixture {
        let env = ProcessInfo.processInfo.environment
        let audioPath = env["KG_UI_TEST_PODCAST_AUDIO"]
            ?? "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts/ep_1_flash.m4a"
        let subtitlePath = env["KG_UI_TEST_PODCAST_SUBTITLE"]
            ?? "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts/ep_1_flash.srt"
        let durationSec = env["KG_UI_TEST_PODCAST_DURATION"].flatMap(Double.init) ?? 1_034.6
        let audioURL = URL(fileURLWithPath: audioPath)
        let subtitleURL = URL(fileURLWithPath: subtitlePath)
        guard FileManager.default.fileExists(atPath: audioURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: audioURL.path])
        }
        guard FileManager.default.fileExists(atPath: subtitleURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: subtitleURL.path])
        }
        return PlayablePodcastFixture(
            audioURL: audioURL,
            subtitleURL: subtitleURL,
            durationSec: durationSec,
            seriesTitle: env["KG_UI_TEST_PODCAST_SERIES_TITLE"] ?? "Atomic Habits",
            episodeTitle: env["KG_UI_TEST_PODCAST_EPISODE_TITLE"] ?? "Actual Lab Episode",
            hostNames: [env["KG_UI_TEST_PODCAST_HOST"] ?? "Lab Podcast"]
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
