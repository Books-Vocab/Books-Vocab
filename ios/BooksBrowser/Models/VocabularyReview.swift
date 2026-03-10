//
//  VocabularyReview.swift
//  BooksBrowser
//
//  本地簡化版間隔複習規則與顯示輔助。
//

import Foundation
import SwiftData

enum ReviewFeedback: Int, Codable {
    case forgot = 0
    case remembered = 1
}

enum VocabularyCardMode: String, Codable {
    case recognition
    case production

    var title: String {
        switch self {
        case .recognition:
            return "Recognition"
        case .production:
            return "Production"
        }
    }

    var localizedTitle: String {
        switch self {
        case .recognition:
            return L10n.string("辨識")
        case .production:
            return L10n.string("產出")
        }
    }
}

enum VocabularyReviewState: String, CaseIterable, Identifiable {
    case unlearned
    case due
    case reviewed

    var id: String { rawValue }

    var title: String {
        switch self {
        case .unlearned: return L10n.string("未學習")
        case .due: return L10n.string("待複習")
        case .reviewed: return L10n.string("已複習")
        }
    }
}

struct VocabularyReviewSnapshot {
    let intervalHours: Double
    let nextReviewAt: Date
    let lastReviewedAt: Date?
    let reviewCount: Int
    let lapseCount: Int
    let streak: Int
    let lastFeedback: ReviewFeedback?

    var isDue: Bool {
        nextReviewAt <= Date()
    }
}

enum VocabularyReviewPolicy {
    static let initialIntervalHours: Double = 12
    static let rememberedMultiplier: Double = 1.9
    static let forgotMultiplier: Double = 0.45
    static let minimumIntervalHours: Double = 6
    static let maximumIntervalHours: Double = 24 * 60

    static func nextIntervalHours(
        currentIntervalHours: Double,
        feedback: ReviewFeedback
    ) -> Double {
        let base = max(currentIntervalHours, minimumIntervalHours)
        let multiplier = feedback == .remembered ? rememberedMultiplier : forgotMultiplier
        return min(maximumIntervalHours, max(minimumIntervalHours, base * multiplier))
    }
}

extension VocabularyEntry {
    var reviewSnapshot: VocabularyReviewSnapshot {
        VocabularyReviewSnapshot(
            intervalHours: reviewIntervalHours,
            nextReviewAt: nextReviewAt,
            lastReviewedAt: lastReviewedAt,
            reviewCount: reviewCount,
            lapseCount: lapseCount,
            streak: reviewStreak,
            lastFeedback: ReviewFeedback(rawValue: lastReviewFeedbackRaw)
        )
    }

    var isReviewDue: Bool {
        reviewSnapshot.isDue
    }

    var reviewState: VocabularyReviewState {
        if reviewCount == 0 {
            return .unlearned
        }
        return isReviewDue ? .due : .reviewed
    }

    func applyReviewFeedback(_ feedback: ReviewFeedback, now: Date = Date(), meta: VocabularyReviewMeta? = nil) {
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

        meta?.applyReviewFeedback(feedback, now: now)
    }
}

enum VocabularyReviewMetaHelper {
    @MainActor
    static func reviewMeta(for entry: VocabularyEntry, in context: ModelContext) -> VocabularyReviewMeta? {
        let entryId = entry.id
        let allMeta = (try? context.fetch(FetchDescriptor<VocabularyReviewMeta>())) ?? []
        return allMeta.first { $0.id == entryId }
    }

    @MainActor
    static func createReviewMeta(for entry: VocabularyEntry, in context: ModelContext) {
        let meta = VocabularyReviewMeta(
            id: entry.id,
            wordKey: entry.word.lowercased(),
            context: entry.context,
            bookTitle: entry.bookTitle,
            chapterTitle: entry.chapterTitle,
            originalDateAdded: entry.dateAdded,
            pronunciation: entry.pronunciation
        )
        meta.reviewIntervalHours = entry.reviewIntervalHours
        meta.nextReviewAt = entry.nextReviewAt
        meta.lastReviewedAt = entry.lastReviewedAt
        meta.reviewCount = entry.reviewCount
        meta.lapseCount = entry.lapseCount
        meta.reviewStreak = entry.reviewStreak
        meta.lastReviewFeedbackRaw = entry.lastReviewFeedbackRaw
        context.insert(meta)
    }

    static func deleteReviewMeta(for entry: VocabularyEntry, in context: ModelContext) {
        let entryId = entry.id
        let allMeta = (try? context.fetch(FetchDescriptor<VocabularyReviewMeta>())) ?? []
        if let meta = allMeta.first(where: { $0.id == entryId }) {
            context.delete(meta)
        }
    }

    static func deleteAllReviewMeta(in context: ModelContext) {
        let allMeta = (try? context.fetch(FetchDescriptor<VocabularyReviewMeta>())) ?? []
        for meta in allMeta {
            context.delete(meta)
        }
    }
}

extension Date {
    func reviewRelativeDescription(now: Date = Date()) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        return formatter.localizedString(for: self, relativeTo: now)
    }
}
