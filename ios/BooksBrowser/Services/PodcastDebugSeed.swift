#if DEBUG
import SwiftData

enum PodcastDebugSeed {
    @MainActor
    static func seedIfNeeded(context: ModelContext) {
        let descriptor = FetchDescriptor<PodcastSeries>()
        guard (try? context.fetchCount(descriptor)) == 0 else { return }

        let series = PodcastSeries(
            remoteId: "debug-flow",
            title: "Flow: The Psychology of Optimal Experience",
            hostNames: ["Maya", "Kai"]
        )
        series.color = "#5B8C5A"
        series.coverPattern = "waves"
        series.episodeCount = 1
        series.totalDurationSec = 1420
        context.insert(series)

        let episode = PodcastEpisode(
            remoteId: "debug-flow-ep1",
            episodeNumber: 1,
            title: "The Happiness Trap",
            durationSec: 1420
        )
        episode.series = series
        episode.audioAvailable = true
        episode.subtitleAvailable = true
        if let audioURL = Bundle.main.url(forResource: "debug_podcast", withExtension: "mp3") {
            episode.localAudioPath = audioURL.absoluteString
        }
        if let srtURL = Bundle.main.url(forResource: "debug_podcast", withExtension: "srt") {
            episode.localSubtitlePath = srtURL.absoluteString
        }
        context.insert(episode)

        try? context.save()
    }
}
#endif
