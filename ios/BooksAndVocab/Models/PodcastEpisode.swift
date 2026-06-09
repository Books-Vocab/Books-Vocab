import Foundation
import SwiftData

@Model
final class PodcastEpisode {
    var id: UUID = UUID()
    // Defaults on every stored property — see PodcastSeries for rationale.
    var remoteId: String = ""
    var series: PodcastSeries?
    var episodeNumber: Int = 0
    var title: String = ""
    var durationSec: Double = 0
    var audioURL: String?
    var localAudioPath: String?
    var subtitleURL: String?
    var localSubtitlePath: String?
    var audioAvailable: Bool = false
    var subtitleAvailable: Bool = false
    /// SRT content cached from metadata.json when the backend embeds it.
    /// Nil for legacy series uploaded before the embed change — caller
    /// must fall back to fetching from subtitleURL in that case.
    var inlineSubtitle: String?
    /// Free-tier preview availability (ep 1 only — see backend podcast_access).
    /// When true the backend `audio` endpoint serves a pre-generated ~3-min
    /// `preview.*` clip to free-tier callers. Defaults false for legacy series
    /// (and every ep > 1) whose metadata predates the preview pipeline.
    var previewAvailable: Bool = false
    /// Duration of the preview clip in seconds (0 when unknown / no preview).
    var previewDurationSec: Double = 0
    var createdAt: Date = Date()
    var updatedAt: Date = Date()

    init(remoteId: String, episodeNumber: Int, title: String, durationSec: Double) {
        self.remoteId = remoteId
        self.episodeNumber = episodeNumber
        self.title = title
        self.durationSec = durationSec
    }

    var displayTitle: String {
        "Ep \(episodeNumber) · \(title)"
    }
}
