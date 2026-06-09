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
    /// 綁定的單字本 remoteId（nil = 尚未綁定，待 seed 固化）。Server 不下發，純本機偏好
    /// （與 isFollowed 同屬本機欄位，reconcile upsert 不覆寫）。選詞 / 底線 / cache 一律
    /// 認此綁定本 —— 一個系列只歸屬一本單字本。見 NotebookBindable。
    var preferredNotebookId: String?
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

extension PodcastSeries: NotebookBindable {}
