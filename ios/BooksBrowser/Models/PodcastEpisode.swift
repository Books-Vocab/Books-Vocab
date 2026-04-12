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
    var audioURL: String?
    var localAudioPath: String?
    var subtitleURL: String?
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
