import SwiftData
import Foundation

@Model
final class PodcastProgress {
    // Note: NO @Attribute(.unique) — CloudKit doesn't support unique constraints.
    // Uniqueness is enforced in application code (fetch by episodeRemoteId before insert).
    var episodeRemoteId: String = ""
    var lastPlayedTime: Double = 0
    var completed: Bool = false
    var updatedAt: Date = Date()

    init(episodeRemoteId: String, lastPlayedTime: Double = 0, completed: Bool = false) {
        self.episodeRemoteId = episodeRemoteId
        self.lastPlayedTime = lastPlayedTime
        self.completed = completed
        self.updatedAt = Date()
    }
}
