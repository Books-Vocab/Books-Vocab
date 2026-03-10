//
//  VocabularyReviewMeta.swift
//  BooksBrowser
//
//  CloudKit 同步的詞彙複習狀態與來源資訊。
//

import Foundation
import SwiftData

@Model
final class VocabularyReviewMeta {
    var id: UUID
    var wordKey: String

    // 來源資訊（後端不存）
    var context: String = ""
    var bookTitle: String = ""
    var chapterTitle: String? = nil
    var originalDateAdded: Date = Date()
    var pronunciation: String? = nil

    // 複習狀態（純本地，後端完全不存）
    var reviewIntervalHours: Double = VocabularyReviewPolicy.initialIntervalHours
    var nextReviewAt: Date = Date().addingTimeInterval(VocabularyReviewPolicy.initialIntervalHours * 3600)
    var lastReviewedAt: Date? = nil
    var reviewCount: Int = 0
    var lapseCount: Int = 0
    var reviewStreak: Int = 0
    var lastReviewFeedbackRaw: Int = -1

    init(
        id: UUID,
        wordKey: String,
        context: String = "",
        bookTitle: String = "",
        chapterTitle: String? = nil,
        originalDateAdded: Date = Date(),
        pronunciation: String? = nil
    ) {
        self.id = id
        self.wordKey = wordKey
        self.context = context
        self.bookTitle = bookTitle
        self.chapterTitle = chapterTitle
        self.originalDateAdded = originalDateAdded
        self.pronunciation = pronunciation
    }
}

extension VocabularyReviewMeta {
    func applyReviewFeedback(_ feedback: ReviewFeedback, now: Date = Date()) {
        let updatedInterval = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: reviewIntervalHours,
            feedback: feedback
        )

        reviewIntervalHours = updatedInterval
        nextReviewAt = now.addingTimeInterval(updatedInterval * 3600)
        lastReviewedAt = now
        reviewCount += 1
        lastReviewFeedbackRaw = feedback.rawValue

        switch feedback {
        case .remembered:
            reviewStreak += 1
        case .forgot:
            lapseCount += 1
            reviewStreak = 0
        }
    }
}
