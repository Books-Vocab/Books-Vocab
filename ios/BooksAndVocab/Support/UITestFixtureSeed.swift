#if os(iOS)
import Foundation
import SwiftData

/// Bridges the existing fixture system into the live SwiftData container for UI tests.
/// Triggered by launch arguments when `-ui-testing` is active.
@MainActor
enum UITestFixtureSeed {
    /// Parse `-seedFixture:<domain>:<id>` arguments and inject matching fixtures.
    static func injectIfNeeded(into container: ModelContainer, arguments: [String]) {
        guard AppRuntimeOptions.isUITesting(arguments: arguments) else { return }

        for arg in arguments {
            guard arg.hasPrefix("-seedFixture:") else { continue }
            let remainder = arg.dropFirst("-seedFixture:".count)
            let parts = remainder.split(separator: ":", maxSplits: 1).map(String.init)
            guard parts.count == 2 else { continue }
            let domain = parts[0]
            let id = parts[1]

            switch domain {
            case "bookshelf":
                seedBookshelf(id, into: container)
            case "podcast":
                seedPodcast(id, into: container)
            default:
                AppLog.app.warning("Unknown UI-test fixture domain: \(domain)")
            }
        }
    }

    // MARK: - Bookshelf

    @MainActor
    private static func seedBookshelf(_ id: String, into container: ModelContainer) {
        guard let fixtureID = BookshelfFixtureID(rawValue: id) else {
            AppLog.app.warning("Unknown bookshelf fixture ID: \(id)")
            return
        }
        let model = BookshelfFixtures.renderModel(for: fixtureID)
        let context = container.mainContext
        for source in model.books {
            // Re-create Book so it is not already associated with the fixture's
            // in-memory container.
            let book = Book(
                title: source.title,
                author: source.author,
                fileName: source.epubFileName,
                format: source.format
            )
            book.progression = source.progression
            book.dateAdded = source.dateAdded
            book.dateLastRead = source.dateLastRead
            context.insert(book)
        }
        do {
            try context.save()
            AppLog.app.info("UI-test fixture seeded: bookshelf.\(id) (\(model.books.count) books)")
        } catch {
            AppLog.app.error("Failed to seed bookshelf fixture: \(error)")
        }
    }

    // MARK: - Podcast

    @MainActor
    private static func seedPodcast(_ id: String, into container: ModelContainer) {
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
            series.totalDurationSec = 2
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
            episode.previewDurationSec = 2
            episode.localAudioPath = audioURL.path
            episode.subtitleAvailable = true
            episode.inlineSubtitle = subtitle

            context.insert(series)
            context.insert(episode)
            try context.save()
            AuthManager.shared.login(userId: "ui-podcast-free", token: "ui-podcast-free-token")
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
