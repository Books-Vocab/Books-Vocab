//
//  ReviewRecord.swift
//  Books & Vocab
//
//  每次複習的事件紀錄，用於統計日曆和活動歷史。
//

import Foundation
import SwiftData

@Model
final class ReviewRecord {
    #Index<ReviewRecord>([\.notebookId], [\.dayKey], [\.reviewedAt])

    var id: UUID
    var word: String
    var entryID: UUID?
    var feedback: Int          // 0=forgot, 1=remembered
    var reviewedAt: Date
    var dayKey: String         // "yyyy-MM-dd" 冗餘索引，加速按日查詢
    var notebookId: String = "default"

    // 複習當下固化的後端 card id。事件自包含,不再靠上報時 entryID→entry→kgCardId 即時
    // 三段反查 —— 卡一離場(刪除/換 notebook/未同步)反查就退化成 nil 致後端 card_id NULL。
    // legacy 紀錄為 nil(上報時回退舊反查)。
    var kgCardId: String?

    // 複習當下的 SRS 前後快照。研究「每張卡學習曲線/遺忘規律」需逐筆事件自包含,不能只靠
    // 卡片現狀聚合反推。全 optional:legacy 紀錄 nil,新紀錄在 session flush 固化。
    var intervalBefore: Double?
    var intervalAfter: Double?
    var nextReviewBefore: Date?
    var nextReviewAfter: Date?
    var reviewCountAfter: Int?
    var streakAfter: Int?
    var lapseAfter: Int?

    /// When the backend acknowledged this event. `nil` = still owed to the server.
    ///
    /// Review events are append-only and de-duplicated server-side by `event_id`,
    /// so without this watermark the client had no way to tell "already uploaded"
    /// from "new" and re-sent its entire history every sync (production: 9,542
    /// events, ~3.4MB, 10 sequential PATCHes, 15.4s of a 17s sync, all skipped
    /// server-side). Optional so the schema change is a lightweight migration:
    /// existing rows arrive as `nil` and drain in one final full push, which is
    /// exactly the old cost and cannot lose an event that never made it up.
    var pushedAt: Date?

    init(
        word: String,
        entryID: UUID?,
        feedback: Int,
        reviewedAt: Date = Date(),
        kgCardId: String? = nil,
        intervalBefore: Double? = nil,
        intervalAfter: Double? = nil,
        nextReviewBefore: Date? = nil,
        nextReviewAfter: Date? = nil,
        reviewCountAfter: Int? = nil,
        streakAfter: Int? = nil,
        lapseAfter: Int? = nil
    ) {
        self.id = UUID()
        self.word = word
        self.entryID = entryID
        self.feedback = feedback
        self.reviewedAt = reviewedAt
        self.dayKey = Self.makeDayKey(from: reviewedAt)
        self.kgCardId = kgCardId
        self.intervalBefore = intervalBefore
        self.intervalAfter = intervalAfter
        self.nextReviewBefore = nextReviewBefore
        self.nextReviewAfter = nextReviewAfter
        self.reviewCountAfter = reviewCountAfter
        self.streakAfter = streakAfter
        self.lapseAfter = lapseAfter
    }

    static func makeDayKey(from date: Date) -> String {
        AppDateFormatters.dayKey.string(from: date)
    }
}
