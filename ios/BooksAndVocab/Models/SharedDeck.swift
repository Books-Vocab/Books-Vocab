//
//  SharedDeck.swift
//  Books & Vocab
//
//  共享牌組（Explore）唯讀本機 mirror。
//
//  這是一個**獨立** @Model，刻意 **不** reuse `Notebook @Model` —— 官方/公開牌組
//  絕不可滲進私人 Notebooks 的 `@Query`。兩者是不同型別，`FetchDescriptor<Notebook>`
//  在型別層就永遠看不到 SharedDeck row（結構性隔離，非靠 predicate）。
//
//  所有 stored property 都帶 default：對齊 `PodcastSeries` / `Notebook` 的 SwiftData
//  lightweight-migration 慣例（此 model 與 VocabularyEntry / Notebook / Podcast* 共用
//  同一 LocalStore，未版本化改動會使既有 store 開啟失敗 → store reset）。此 model
//  只在本機 LocalStore（cloudKitDatabase: .none），不上 CloudKit —— 純遠端目錄快取。
//

import Foundation
import SwiftData

@Model
final class SharedDeck {
    var id: UUID = UUID()
    /// 伺服器鑄造的 deckId（`^[A-Za-z0-9_-]{1,64}$`）。reconcile / detail push 的穩定鍵。
    var remoteId: String = ""
    var title: String = ""
    /// 發布者顯示名（官方牌組通常為 nil，UI 顯示官方徽章）。runtime 資料，非 i18n key。
    var authorLabel: String?
    /// 官方策展徽章 —— server-authoritative（source enum 驅動），永不 client-settable。
    var isOfficial: Bool = false
    /// 粗分類 enum：'language' | 'exam' | 'phrase' | 'custom'（filter 用）。lenient：未知值原樣存。
    var category: String?
    /// 定向語言對，如 'en-zh'（filter 用）。
    var languagePair: String?
    var tags: [String] = []
    var cardCount: Int = 0
    var downloadCount: Int = 0
    var ratingAvg: Double?
    var ratingCount: Int = 0
    /// Procedural cover（復用 NotebookCoverView）——**非** image path。
    var color: String?
    var coverPattern: String?
    /// 伺服器端 updatedAt（已 parse 成 Date；nil = 伺服器未下發或無法解析）。UI 走 LocaleAwareFormatter。
    var updatedAt: Date?
    /// server browse 排序位置（reconcile 時以 server 回傳次序固化，供本機 grid 穩定排序）。
    var sortOrder: Int = 0
    /// 本機 tombstone 旗標（server 不再回報此 deck → soft-delete；鏡射 PodcastSeries.isSoftDeleted）。
    @Attribute(originalName: "isDeleted")
    var isSoftDeleted: Bool = false
    /// 最近一次 reconcile upsert 時間（本機欄位）。
    var syncedAt: Date = Date()

    init(remoteId: String, title: String) {
        self.remoteId = remoteId
        self.title = title
    }
}
