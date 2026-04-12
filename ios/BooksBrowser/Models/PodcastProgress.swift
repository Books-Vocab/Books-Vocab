import SwiftData
import Foundation

@Model
final class PodcastProgress {
    @Attribute(.unique) var episodeRemoteId: String = ""
    var lastPlayedTime: Double = 0
    var completed: Bool = false
    var updatedAt: Date = Date()

    init(episodeRemoteId: String, lastPlayedTime: Double = 0, completed: Bool = false) {
        self.episodeRemoteId = episodeRemoteId
        self.lastPlayedTime = lastPlayedTime
        self.updatedAt = Date()
    }
}
