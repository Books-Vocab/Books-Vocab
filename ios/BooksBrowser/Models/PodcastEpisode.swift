import Foundation
import SwiftData

@Model
final class PodcastEpisode {
    var id: UUID = UUID()
    var remoteId: String
    var series: PodcastSeries?
    var episodeNumber: Int
    var title: String
    var durationSec: Double
    var audioURL: String?       // "https://wordnexus.lol/api/podcast-media/{series_id}/ep_{num}/audio.mp3"
    var localAudioPath: String?
    var subtitleURL: String?    // "https://wordnexus.lol/api/podcasts/{series_id}/{ep_num}/subtitle"
    var localSubtitlePath: String?
    var audioAvailable: Bool = false
    var subtitleAvailable: Bool = false
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
