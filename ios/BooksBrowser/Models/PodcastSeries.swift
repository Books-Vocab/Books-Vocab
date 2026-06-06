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
    /// Local cache path of the downloaded remote cover (set by PodcastSyncService
    /// after fetching `coverImageURL`). NotebookCoverView renders this over the
    /// procedural color/pattern when present.
    var coverImagePath: String?
    /// Remote cover proxy path from the server (`/api/podcasts/<sid>/cover`), or
    /// nil for legacy/pre-cover series. Drives the one-time download into
    /// `coverImagePath`; nil → fall back to procedural color/pattern cover.
    var coverImageURL: String?
    var hostNames: [String] = []
    var episodeCount: Int = 0
    var totalDurationSec: Double = 0
    var sortOrder: Int = 0
    /// 使用者「追蹤」標記。Server 不下發此欄位，純本機偏好。
    /// Series list 排序：isFollowed desc → sortOrder asc。
    var isFollowed: Bool = false
    var createdAt: Date = Date()
    var updatedAt: Date = Date()
    @Attribute(originalName: "isDeleted")
    var isSoftDeleted: Bool = false

    @Relationship(deleteRule: .cascade, inverse: \PodcastEpisode.series)
    var episodes: [PodcastEpisode] = []

    init(remoteId: String, title: String, hostNames: [String]) {
        self.remoteId = remoteId
        self.title = title
        self.hostNames = hostNames
    }
}
