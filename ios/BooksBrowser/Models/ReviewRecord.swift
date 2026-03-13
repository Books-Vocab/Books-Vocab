//
//  ReviewRecord.swift
//  BooksBrowser
//
//  每次複習的事件紀錄，用於統計日曆和活動歷史。
//

import Foundation
import SwiftData

@Model
final class ReviewRecord {
    #Index<ReviewRecord>(
        [\.dayKey],
        [\.reviewedAt]
    )

    var id: UUID
    var word: String
    var entryID: UUID?
    var feedback: Int          // 0=forgot, 1=remembered
    var reviewedAt: Date
    var dayKey: String         // "yyyy-MM-dd" 冗餘索引，加速按日查詢

    init(word: String, entryID: UUID?, feedback: Int, reviewedAt: Date = Date()) {
        self.id = UUID()
        self.word = word
        self.entryID = entryID
        self.feedback = feedback
        self.reviewedAt = reviewedAt
        self.dayKey = Self.makeDayKey(from: reviewedAt)
    }

    static func makeDayKey(from date: Date) -> String {
        Self.dayFormatter.string(from: date)
    }

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()
}
