import SwiftData
import Foundation

@Model
final class PodcastProgress {
    // NO @Attribute(.unique) — CloudKit does not support unique constraints;
    // having one aborts ModelContainer init with 134060 and wipes the store.
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
