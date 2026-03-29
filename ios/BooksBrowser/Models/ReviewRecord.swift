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
    // Note: #Index requires iOS 18+. Omitted for iOS 17 compatibility.

    var id: UUID
    var word: String
    var entryID: UUID?
    var feedback: Int          // 0=forgot, 1=remembered
    var reviewedAt: Date
    var dayKey: String         // "yyyy-MM-dd" 冗餘索引，加速按日查詢
    var notebookId: String = "default"

    init(word: String, entryID: UUID?, feedback: Int, reviewedAt: Date = Date()) {
        self.id = UUID()
        self.word = word
        self.entryID = entryID
        self.feedback = feedback
        self.reviewedAt = reviewedAt
        self.dayKey = Self.makeDayKey(from: reviewedAt)
    }

    static func makeDayKey(from date: Date) -> String {
        AppDateFormatters.dayKey.string(from: date)
    }
}
