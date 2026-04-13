import Foundation
import SwiftData

@Model
final class PodcastSeries {
    var id: UUID = UUID()
    // Defaults on every stored property — SwiftData lightweight migration
    // fails otherwise when new fields land, and this store is shared with
    // VocabularyEntry / ReviewRecord / Notebook.
    var remoteId: String = ""
    var title: String = ""
    var color: String?
    var coverPattern: String?
    var coverImagePath: String?
    var hostNames: [String] = []
    var episodeCount: Int = 0
    var totalDurationSec: Double = 0
    var sortOrder: Int = 0
    var createdAt: Date = Date()
    var updatedAt: Date = Date()
    var isDeleted: Bool = false

    @Relationship(deleteRule: .cascade, inverse: \PodcastEpisode.series)
    var episodes: [PodcastEpisode] = []

    init(remoteId: String, title: String, hostNames: [String]) {
        self.remoteId = remoteId
        self.title = title
        self.hostNames = hostNames
    }
}
